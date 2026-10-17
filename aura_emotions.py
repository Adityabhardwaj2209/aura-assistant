"""Transparent, rule-based response styles. No claim of real feelings."""
from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parent
CONTROL = ROOT/'brain_data'/'emotion_control.json'
TONES = ('calm', 'cheerful', 'focused', 'supportive')
CURRENT = ContextVar('aura_emotion_style', default=None)


def atomic_json(path, data):
    path = Path(path)
    parent = ROOT/'brain_data'
    if path.parent != parent or parent.is_symlink() or path.is_symlink():
        raise ValueError('Unsupported settings path.')
    parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=parent, delete=False) as out:
            temporary = Path(out.name)
            json.dump(data, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def control():
    try:
        data = json.loads(CONTROL.read_text(encoding='utf-8'))
        if isinstance(data, dict) and data.get('mode') in ('auto', 'manual', 'off'):
            if data.get('tone', 'calm') in TONES:
                return {'mode': data['mode'], 'tone': data.get('tone', 'calm')}
    except (OSError, ValueError):
        pass
    return {'mode': 'auto', 'tone': 'calm'}


def configure(value):
    value = value.strip().lower()
    if value in ('auto', 'off'):
        data = {'mode': value, 'tone': 'calm'}
    elif value in TONES:
        data = {'mode': 'manual', 'tone': value}
    else:
        raise ValueError('Use /emotion auto, off, calm, cheerful, focused or supportive.')
    atomic_json(CONTROL, data)
    return data


def select_style(message):
    """Only coarse text cues; quoted words, sarcasm and mixed language can fool it."""
    cfg = control()
    text = message.casefold()
    if cfg['mode'] == 'off':
        return {'tone': None, 'reason': 'automatic style disabled'}
    # Plain first-person expressions take priority over a cheerful preference.
    if re.search(r"\b(i am|i'm|i feel|feeling|main|mai|mujhe)\s+(?:very\s+|bahut\s+)?(sad|stressed|anxious|upset|lonely|overwhelmed|scared|dukhi|pareshan)\b", text) or re.search(r'\b(tension ho rahi|help me calm down|please be supportive)\b', text):
        return {'tone': 'supportive', 'reason': 'support requested or expressed distress'}
    if cfg['mode'] == 'manual':
        return {'tone': cfg['tone'], 'reason': 'user selected style'}
    if re.search(r'\b(i passed|i got selected|i am happy|i\x27m happy|i feel happy|i won|exam clear ho gaya|job mil gayi)\b', text):
        return {'tone': 'cheerful', 'reason': 'user shared positive news'}
    if re.search(r'\b(debug|traceback|bug|coding|implement|solve|exam|deadline|plan|error)\b', text):
        return {'tone': 'focused', 'reason': 'task-focused request'}
    return {'tone': 'calm', 'reason': 'default response style'}


def style_override(default):
    state = CURRENT.get()
    return state['tone'] if state and state.get('tone') in TONES else default
