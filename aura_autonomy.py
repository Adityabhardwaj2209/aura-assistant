"""Brain chooses response style and invokes fixed local maintenance tools."""
import asyncio
import contextlib
import json
import aura_emotions as emotions
import aura_selfcare as care


async def managed_route_stream(original, client, model, user, history, preferences):
    from aura_perception import perception_reply
    vision_reply = await asyncio.to_thread(perception_reply, user)
    if vision_reply is not None:
        yield {'type':'route','name':'live_vision','query':user,'emotion':'focused'}
        yield {'type':'token','text':vision_reply}
        return
    from aura_body import command_reply
    body_reply = await asyncio.to_thread(command_reply, user)
    if body_reply is not None:
        yield {'type':'route', 'name':'virtual_body', 'query':user, 'emotion':'focused'}
        yield {'type':'token', 'text':body_reply}
        return
    words = user.strip().split()
    command = words[0].lower() if words else ''
    if command in ('/emotion', '/heart', '/selfcheck', '/repair', '/autocare'):
        yield {'type':'route', 'name':'selfcare', 'query':command, 'emotion':'focused'}
        if command in ('/emotion', '/heart'):
            if len(words)>2: raise ValueError('Use /emotion followed by one mode or tone.')
            state = emotions.configure(words[1]) if len(words)==2 else emotions.control()
            text = 'Heart response style: '+json.dumps(state)+'. These are communication styles, not real feelings.'
        elif command == '/autocare':
            if len(words)!=2 or words[1].lower() not in ('on','off'):
                raise ValueError('Use /autocare on or /autocare off.')
            await asyncio.to_thread(care.set_enabled, words[1].lower()=='on')
            text = 'Automatic known repairs '+words[1].lower()+'. Use run_aura_managed.py to enable startup/periodic checks.'
        else:
            if len(words)!=1: raise ValueError('Use '+command+' without extra arguments.')
            result = await asyncio.to_thread(care.repair_known) if command=='/repair' else None
            text = await asyncio.to_thread(care.report, result)
        yield {'type':'token', 'text':text}
        return
    # No command from document passages or model output reaches this parser.
    try:
        await asyncio.to_thread(care.tick)
    except (OSError, ValueError):
        care.record('maintenance_unavailable')
    state = emotions.select_style(user)
    token = emotions.CURRENT.set(state)
    try:
        async with contextlib.aclosing(original(client, model, user, history, preferences)) as stream:
            async for event in stream:
                if event.get('type') == 'route':
                    event = dict(event, emotion=state['tone'] or 'manual Heart setting')
                yield event
    except asyncio.CancelledError:
        raise
    except Exception:
        # Log a category only; never persist the exception text or user prompt.
        care.record('request_failed')
        raise
    finally:
        emotions.CURRENT.reset(token)
