"""AURA Heart: a user-controlled communication style, not simulated sentience."""
import argparse
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'brain_data' / 'heart.json'
TONES = {
    'calm': 'Speak warmly and calmly. Use reassuring, clear language without exaggeration.',
    'cheerful': 'Use a light, friendly style. Keep enthusiasm natural and avoid excessive praise.',
    'focused': 'Be direct and practical. Prioritize clear steps, useful examples and the current goal.',
    'supportive': 'Acknowledge feelings the user explicitly expresses. Be patient and offer manageable next steps.',
}
DEFAULT = {'tone': 'calm', 'verbosity': 'balanced'}


def settings():
    try:
        data = json.loads(CONFIG.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return DEFAULT.copy()
    except (OSError, ValueError):
        return DEFAULT.copy()
    return {
        'tone': data.get('tone') if data.get('tone') in TONES else DEFAULT['tone'],
        'verbosity': data.get('verbosity') if data.get('verbosity') in ('short','balanced','detailed') else DEFAULT['verbosity'],
    }


def configure(tone=None, verbosity=None):
    data = settings()
    if tone is not None:
        if tone not in TONES:
            raise ValueError('Choose calm, cheerful, focused or supportive.')
        data['tone'] = tone
    if verbosity is not None:
        if verbosity not in ('short','balanced','detailed'):
            raise ValueError('Choose short, balanced or detailed.')
        data['verbosity'] = verbosity
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=CONFIG.parent, suffix='.tmp', delete=False) as out:
            temporary = Path(out.name)
            json.dump(data, out, ensure_ascii=False, indent=2)
        os.replace(temporary, CONFIG)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return data


def heart_prompt():
    data = settings()
    from aura_emotions import style_override
    data['tone'] = style_override(data['tone'])
    detail = {
        'short': 'Prefer brief answers unless the task requires more detail.',
        'balanced': 'Match explanation length to the question and user needs.',
        'detailed': 'For complex requests give structured explanations and concrete examples.',
    }[data['verbosity']]
    return (
        'AURA COMMUNICATION STYLE: '+TONES[data['tone']]+' '+detail+' '
        'Treat these settings as presentation preferences, not evidence about the user. '
        'Respond to the actual message: if the user expresses distress, prioritize a calm, '
        'supportive tone even when the selected style is cheerful. Do not diagnose or '
        'claim to detect hidden emotions. Ask a focused question only when useful. '
        'Respect the user\'s autonomy and their relationships with other people. '
        'Do not guilt, pressure, flatter excessively, or imply exclusive attachment. '
        'Be transparent when asked: AURA is software and has no real feelings, '
        'heartbeat, subjective experience or consciousness. You may be warm without '
        'claiming to suffer, miss the user, or need their attention. '
        'Do not invent personal memories, capabilities or actions. '
        'Accuracy and the user\'s explicit instructions take priority over style.\n'
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='AURA communication preferences')
    parser.add_argument('--tone', choices=list(TONES))
    parser.add_argument('--verbosity', choices=['short','balanced','detailed'])
    args = parser.parse_args()
    if args.tone or args.verbosity:
        print(json.dumps(configure(args.tone, args.verbosity), indent=2))
    else:
        print(json.dumps(settings(), indent=2))
