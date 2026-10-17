"""Inspectable self-care. Fixed repair recipes only, never model-generated code."""
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parent
FILES = ('run_aura.py', 'aura_router.py', 'aura_brain.py', 'aura_heart.py', 'aura_web.py',
         'phase3_web.py', 'aura_emotions.py', 'aura_selfcare.py', 'aura_autonomy.py')
DEFAULTS = {'heart.json': {'tone':'calm', 'verbosity':'balanced'},
            'emotion_control.json': {'mode':'auto', 'tone':'calm'},
            'selfcare_control.json': {'enabled':True}}
_ACTIVE = False
_LAST_CHECK = 0.0
_LOCK = threading.RLock()


def safe_path(relative):
    path = ROOT/relative
    if not path.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('Path leaves the AURA project.')
    if any(p.is_symlink() for p in [path, *path.parents] if p != ROOT.parent):
        raise ValueError('Self-care will not modify symlinked paths.')
    return path


def write_bytes(path, raw):
    path = safe_path(path.relative_to(ROOT))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
            temporary = Path(out.name)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def valid_settings(name, data):
    if not isinstance(data, dict): return False
    if name == 'heart.json':
        return data.get('tone') in ('calm','cheerful','focused','supportive') and data.get('verbosity') in ('short','balanced','detailed')
    if name == 'emotion_control.json':
        return data.get('mode') in ('auto','manual','off') and data.get('tone') in ('calm','cheerful','focused','supportive')
    return type(data.get('enabled')) is bool


def enabled():
    try:
        data = json.loads(safe_path('brain_data/selfcare_control.json').read_text(encoding='utf-8'))
        return data.get('enabled') is True
    except (OSError, ValueError, AttributeError):
        return True


def set_enabled(value):
    with _LOCK:
        write_bytes(safe_path('brain_data/selfcare_control.json'), json.dumps({'enabled':bool(value)}).encode())


def record(code, **counts):
    """No prompts, source contents, API keys, exception messages or filenames."""
    try:
        with _LOCK:
            path = safe_path('brain_data/selfcare_events.json')
            try:
                events = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(events, list): events = []
            except (OSError, ValueError): events = []
            event = {'time':datetime.now(timezone.utc).isoformat(), 'event':code}
            event.update({key:value for key,value in counts.items() if type(value) is int})
            write_bytes(path, json.dumps((events+[event])[-200:], indent=2).encode())
    except (OSError, ValueError):
        pass


def inspect():
    findings = []
    for name in FILES:
        try:
            path = safe_path(name)
            if not path.exists():
                findings.append({'file':name, 'issue':'missing_file', 'repairable':False})
                continue
            source = path.read_text(encoding='utf-8-sig')
            ast.parse(source)
            if name == 'run_aura.py' and "server.app.add_event_handler('startup', ready.set)" in source:
                findings.append({'file':name, 'issue':'legacy_startup_hook', 'repairable':True})
        except SyntaxError as error:
            findings.append({'file':name, 'issue':'python_syntax', 'line':error.lineno, 'repairable':False})
        except (OSError, ValueError):
            findings.append({'file':name, 'issue':'unreadable_or_unsafe_path', 'repairable':False})
    for name in DEFAULTS:
        try:
            path = safe_path('brain_data/'+name)
            if not path.exists(): continue
            data = json.loads(path.read_text(encoding='utf-8'))
            if not valid_settings(name, data): raise ValueError()
        except (OSError, ValueError):
            findings.append({'file':'brain_data/'+name, 'issue':'invalid_style_settings', 'repairable':True})
    for name in ('brain_data/knowledge.db', 'memory.db'):
        try:
            path = safe_path(name)
            if not path.exists(): continue
            with __import__('contextlib').closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
                deadline = time.monotonic()+2
                db.set_progress_handler(lambda: int(time.monotonic()>deadline), 1000)
                result = db.execute('PRAGMA quick_check(1)').fetchone()
                if result != ('ok',):
                    findings.append({'file':name, 'issue':'database_check_failed', 'repairable':False})
        except (OSError, ValueError, sqlite3.Error):
            findings.append({'file':name, 'issue':'database_unavailable_or_check_incomplete', 'repairable':False})
    return findings


def repair_known():
    """Back up exact originals. Compile/parse candidates before atomic replacement."""
    with _LOCK:
        findings = inspect()
        repaired = []
        for finding in findings:
            if not finding['repairable']: continue
            try:
                path = safe_path(finding['file'])
                original = path.read_bytes()
                if finding['issue'] == 'legacy_startup_hook':
                    raw = original.decode('utf-8-sig').replace("server.app.add_event_handler('startup', ready.set)", 'ready.set()').encode('utf-8')
                    ast.parse(raw.decode('utf-8'))
                elif path.name in DEFAULTS:
                    raw = json.dumps(DEFAULTS[path.name], indent=2).encode()
                    assert valid_settings(path.name, json.loads(raw))
                else: continue
                stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
                backup = safe_path('selfcare_backups/'+stamp+'/'+finding['file'])
                write_bytes(backup, original)
                if path.read_bytes() != original:
                    continue  # An editor changed the file; leave the new version alone.
                try:
                    write_bytes(path, raw)
                    check = path.read_bytes()
                    if check != raw: raise OSError('Verification failed')
                except Exception:
                    write_bytes(path, original)
                    raise
                repaired.append(finding['file'])
            except (OSError, ValueError):
                continue
        unresolved = inspect()
        record('known_repair', repaired=len(repaired), unresolved=len(unresolved))
        return {'repaired':repaired, 'unresolved':unresolved}


def activate():
    global _ACTIVE
    _ACTIVE = True


def tick(force=False):
    global _LAST_CHECK
    with _LOCK:
        if not _ACTIVE or not enabled(): return None
        if not force and time.monotonic()-_LAST_CHECK < 300: return None
        _LAST_CHECK = time.monotonic()
        return repair_known()


def report(result=None):
    result = result or {'repaired':[], 'unresolved':inspect()}
    lines = ['AURA self-check: '+str(len(result['repaired']))+' known repairs; '+str(len(result['unresolved']))+' unresolved findings.']
    for name in result['repaired']: lines.append('Repaired with backup: '+name)
    for item in result['unresolved']:
        lines.append(item['file']+': '+item['issue']+(' (known repair available)' if item['repairable'] else ' (needs code review or manual investigation)'))
    lines.append('No generated code was executed. Databases and API keys were not repaired or replaced.')
    return '\n'.join(lines)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='AURA fixed-recipe self-care')
    parser.add_argument('--repair',action='store_true',help='Apply only the known, backed-up repairs')
    args = parser.parse_args()
    print(report(repair_known() if args.repair else None))
