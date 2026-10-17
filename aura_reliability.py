"""Bounded stream waits and user-facing errors; no automatic API retries."""
import asyncio
import contextlib

FIRST_EVENT_SECONDS = 30
WEB_REPLY_SECONDS = 80
IDLE_SECONDS = 40
TURN_SECONDS = 150


def recovery_message(error):
    status = getattr(error, 'status_code', None)
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)) or 'timeout' in type(error).__name__.lower():
        return 'AURA request timed out. Check your connection and retry; for a long web search, ask a narrower question.'
    if status == 429:
        return 'API rate limit reached. Wait briefly, then retry. Check your provider quota if it continues.'
    if status in (401, 403):
        return 'API access rejected. Check the key and model in AURA settings, then retry.'
    if isinstance(status, int) and status >= 500:
        return 'AI provider is temporarily unavailable. Retry shortly.'
    if isinstance(error, ConnectionError) or 'connection' in type(error).__name__.lower():
        return 'Could not reach the AI provider. Check your internet connection, then retry.'
    if isinstance(error, ValueError):
        return str(error)
    return 'AURA could not complete this request. Retry, or choose /docs, /web, /calc or /chat explicitly.'


async def bounded_stream(source):
    """Close on stop/error, propagate cancellation, never replay partial output."""
    try:
        async with contextlib.aclosing(source):
            async with asyncio.timeout(TURN_SECONDS):
                wait = FIRST_EVENT_SECONDS
                while True:
                    try:
                        event = await asyncio.wait_for(anext(source), timeout=wait)
                    except StopAsyncIteration:
                        return
                    if event.get('type') == 'route' and event.get('name') == 'web':
                        wait = WEB_REPLY_SECONDS
                    else:
                        wait = IDLE_SECONDS
                    yield event
    except asyncio.CancelledError:
        raise
    except Exception as error:
        raise ValueError(recovery_message(error)) from None
