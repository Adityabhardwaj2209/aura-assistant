"""AURA Phase 2: local Windows live voice app. Run next to memory.db/avatar GLB."""
import asyncio
import base64
import contextlib
import json
import os
import secrets
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse, FileResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from groq import AsyncGroq
from aura_router import route_stream
from aura_web import web_reply
from aura_brain import build_prompt, initialize as initialize_brain
from brain_routes import install

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'memory.db'
TOKEN = secrets.token_urlsafe(32)
SETTINGS = {'key': '', 'model': 'openai/gpt-oss-20b'}
REPLIES = {}
BUSY = asyncio.Lock()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])


def initialize():
    if DB.exists():
        backup = ROOT / ('memory_before_phase2_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.db')
        with sqlite3.connect(DB) as original, sqlite3.connect(backup) as copy:
            original.backup(copy)
    with sqlite3.connect(DB) as db:
        db.execute('CREATE TABLE IF NOT EXISTS memory (id INTEGER PRIMARY KEY CHECK(id=1), text TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS chat_history (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, content TEXT NOT NULL)')


def messages(limit=None):
    with sqlite3.connect(DB, timeout=10) as db:
        if limit:
            rows = list(reversed(db.execute('SELECT role,content FROM chat_history ORDER BY id DESC LIMIT ?', (limit,)).fetchall()))
        else:
            rows = db.execute('SELECT role,content FROM chat_history ORDER BY id').fetchall()
    return [{'role': role, 'content': content} for role, content in rows]


def preferences():
    with sqlite3.connect(DB, timeout=10) as db:
        row = db.execute('SELECT text FROM memory WHERE id=1').fetchone()
    return row[0] if row else ''


def save_pair(user, reply):
    with sqlite3.connect(DB, timeout=10) as db:
        db.executemany('INSERT INTO chat_history(role,content) VALUES (?,?)', [('user', user), ('assistant', reply)])


def require(request):
    if request.headers.get('X-Aura-Token') != TOKEN:
        raise HTTPException(403, 'Unauthorized local request')
    origin = request.headers.get('origin')
    if origin and origin not in ('http://127.0.0.1:8511', 'http://localhost:8511'):
        raise HTTPException(403, 'Unexpected origin')


def error_hint(error):
    if isinstance(error, ValueError):
        return str(error)
    name = type(error).__name__
    return {
        'AuthenticationError': 'API key rejected. Enter a valid Groq key.',
        'RateLimitError': 'Groq limit reached. Pause and retry later.',
        'APIConnectionError': 'Cannot reach Groq. Check internet.',
        'APITimeoutError': 'Groq request timed out. Retry later.',
        'NotFoundError': 'Model not found. Check the model setting.',
    }.get(name, 'Request failed (' + name + '). Check the server terminal.')


def powershell(script, extra=None):
    env = os.environ.copy()
    env.update(extra or {})
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            env=env, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Windows speech failed. Check installed Windows speech voices.')
    return result.stdout.decode('utf-8-sig').strip()


VOICE_SCRIPT = """$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.Encoding]::UTF8;
Add-Type -AssemblyName System.Speech;
$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;
@($s.GetInstalledVoices() | Where-Object {$_.Enabled} | ForEach-Object {$_.VoiceInfo.Name}) | ConvertTo-Json -Compress;
$s.Dispose();"""

TTS_SCRIPT = """$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Speech;
$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;
try {
if($env:AURA_VOICE){$s.SelectVoice($env:AURA_VOICE)};
$s.Rate=0; $s.SetOutputToWaveFile($env:AURA_WAV);
$text=[System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:AURA_TEXT));
$s.Speak($text);
} finally {$s.Dispose()}"""


@app.get('/')
def index():
    html = (ROOT / 'phase2.html').read_text(encoding='utf-8')
    return HTMLResponse(html.replace('__TOKEN__', TOKEN), headers={'Cache-Control': 'no-store'})


@app.get('/avatar')
def avatar():
    path = ROOT / 'selected_avatar.glb'
    if not path.exists():
        raise HTTPException(404, 'selected_avatar.glb missing; place Phase 2 files in aura-assistant')
    return FileResponse(path, media_type='model/gltf-binary')


@app.get('/worklet.js')
def worklet():
    return Response((ROOT / 'worklet.js').read_text(), media_type='text/javascript')


@app.get('/api/history')
def history(request: Request):
    require(request)
    return {'messages': messages(), 'configured': bool(SETTINGS['key'])}


@app.get('/api/voices')
def voices(request: Request):
    require(request)
    try:
        names = json.loads(powershell(VOICE_SCRIPT))
        return {'voices': [names] if isinstance(names, str) else (names or [])}
    except Exception:
        return {'voices': [], 'warning': 'Windows voice list unavailable; speech may fail.'}


@app.post('/api/config')
async def config(request: Request):
    require(request)
    data = await request.json()
    key, model = str(data.get('key', '')).strip(), str(data.get('model', '')).strip()
    if not key or not model or len(key) > 500 or len(model) > 150:
        raise HTTPException(400, 'Enter key and model')
    if BUSY.locked():
        raise HTTPException(409, 'Wait for the current reply before changing settings')
    SETTINGS.update(key=key, model=model)
    return {'ok': True}


@app.post('/api/turn')
async def turn(request: Request):
    require(request)
    if not SETTINGS['key']:
        raise HTTPException(400, 'Save your Groq key first')
    if BUSY.locked():
        raise HTTPException(409, 'Another reply is running. Please wait briefly.')
    form = await request.form()
    text = str(form.get('text', '')).strip()
    audio = form.get('audio')
    raw = None
    if audio is not None:
        raw = await audio.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPException(400, 'Recording exceeds 5 MB')
        if not raw.startswith(b'RIFF'):
            raise HTTPException(400, 'Expected WAV audio')
    elif not text or len(text) > 6000:
        raise HTTPException(400, 'Enter 1 to 6000 characters')

    def packet(kind, **values):
        return json.dumps({'type': kind, **values}, ensure_ascii=False) + '\n'

    async def generate():
        stream = None
        async with BUSY:
            async with AsyncGroq(api_key=SETTINGS['key'], timeout=90, max_retries=0) as client:
                try:
                    user = text
                    if raw is not None:
                        transcription = await client.audio.transcriptions.create(
                            file=('recording.wav', raw, 'audio/wav'), model='whisper-large-v3-turbo')
                        user = transcription.text.strip()
                    if not user:
                        yield packet('error', message='No speech detected. Try again.')
                        return
                    if len(user) > 6000:
                        yield packet('error', message='Message is too long.')
                        return
                    if await request.is_disconnected():
                        return
                    yield packet('user', text=user)
                    parts = []
                    async with contextlib.aclosing(route_stream(client, SETTINGS['model'], user, messages(12), preferences())) as routed:
                        async for event in routed:
                            if await request.is_disconnected():
                                return
                            if event['type'] == 'route':
                                yield packet('route', name=event['name'], query=event.get('query', ''), emotion=event.get('emotion', ''))
                            elif event['type'] == 'token':
                                parts.append(event['text'])
                                yield packet('token', text=event['text'])
                    reply = ''.join(parts).strip()
                    if not reply:
                        yield packet('error', message='No text reply received.')
                        return
                    if await request.is_disconnected():
                        return
                    save_pair(user, reply)
                    reply_id = secrets.token_urlsafe(18)
                    for old in list(REPLIES):
                        if time.monotonic() - REPLIES[old][1] > 600:
                            del REPLIES[old]
                    while len(REPLIES) >= 20:
                        del REPLIES[next(iter(REPLIES))]
                    REPLIES[reply_id] = (reply, time.monotonic())
                    yield packet('done', text=reply, id=reply_id)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    yield packet('error', message=error_hint(error))
                finally:
                    if stream is not None:
                        with contextlib.suppress(Exception):
                            await stream.close()
    return StreamingResponse(generate(), media_type='application/x-ndjson', headers={'Cache-Control': 'no-store'})


@app.post('/api/speech')
async def speech(request: Request):
    require(request)
    data = await request.json()
    entry = REPLIES.get(str(data.get('id', '')))
    if not entry or time.monotonic() - entry[1] > 600:
        raise HTTPException(400, 'Reply audio expired. Send a new message.')
    voice = str(data.get('voice', ''))
    if len(voice) > 200:
        raise HTTPException(400, 'Invalid voice')

    def synthesize():
        with tempfile.TemporaryDirectory(prefix='aura_speech_') as folder:
            wav = Path(folder) / 'reply.wav'
            powershell(TTS_SCRIPT, {'AURA_TEXT': base64.b64encode(entry[0].encode()).decode(),
                                   'AURA_WAV': str(wav), 'AURA_VOICE': voice})
            return wav.read_bytes()
    try:
        result = await asyncio.to_thread(synthesize)
        return Response(result, media_type='audio/wav', headers={'Cache-Control': 'no-store'})
    except Exception:
        raise HTTPException(503, 'Windows speech failed. Choose another installed voice. Text reply is saved.')


install(app, require, TOKEN)

if __name__ == '__main__':
    import uvicorn
    initialize()
    initialize_brain()
    print('AURA Brain + Web: http://127.0.0.1:8511')
    print('Use /web followed by a question for internet research.')
    print('Knowledge library: http://127.0.0.1:8511/brain')
    print('Phase 1 files are unchanged. Key is entered in the browser and kept only in server memory.')
    uvicorn.run(app, host='127.0.0.1', port=8511)
