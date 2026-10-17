"""Persistent workspace records; separate from existing chat and document databases."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import re
import uuid

ROOT = Path(__file__).resolve().parent
DB = ROOT/'brain_data'/'workspace.db'
KINDS = {'goal','fact','plan','quiz','attempt','patch','evaluation'}


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY,kind TEXT NOT NULL,data TEXT NOT NULL,updated TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS telemetry (id INTEGER PRIMARY KEY,at TEXT,operation TEXT,provider TEXT,model TEXT,ms REAL,ok INTEGER,input_tokens INTEGER,output_tokens INTEGER,error TEXT)')
            yield db
    finally:
        db.close()


def save(kind, data, ident=None):
    if kind not in KINDS or not isinstance(data,dict):raise ValueError('Unsupported record')
    raw=json.dumps(data,ensure_ascii=False,allow_nan=False)
    if len(raw)>150_000:raise ValueError('Record too large')
    ident=ident or uuid.uuid4().hex
    if not isinstance(ident,str) or not re.fullmatch(r'[0-9a-f]{32}',ident):raise ValueError('Invalid record id')
    with connect() as db:
        prior=db.execute('SELECT kind FROM records WHERE id=?',(ident,)).fetchone()
        if prior and prior['kind']!=kind:raise ValueError('Record kind mismatch')
        db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?)',(ident,kind,raw,now()))
    return get(ident,kind)


def get(ident,kind=None):
    if not isinstance(ident,str) or not re.fullmatch(r'[0-9a-f]{32}',ident):raise ValueError('Invalid record id')
    with connect() as db:row=db.execute('SELECT * FROM records WHERE id=?',(ident,)).fetchone()
    if not row or (kind and row['kind']!=kind):raise ValueError('Record not found')
    return dict(id=row['id'],kind=row['kind'],updated=row['updated'],data=json.loads(row['data']))


def records(kind=None):
    if kind and kind not in KINDS:raise ValueError('Unsupported record type')
    with connect() as db:
        rows=db.execute('SELECT * FROM records'+(' WHERE kind=?' if kind else '')+' ORDER BY updated DESC LIMIT 500',(kind,) if kind else ()).fetchall()
    return [dict(id=r['id'],kind=r['kind'],updated=r['updated'],data=json.loads(r['data'])) for r in rows]


def delete(ident,kind):
    get(ident,kind)
    with connect() as db:db.execute('DELETE FROM records WHERE id=? AND kind=?',(ident,kind))


def metric(operation,provider,model,ms,ok,usage=None,error=''):
    usage=usage or {}
    def count(value):return value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else None
    with connect() as db:
        db.execute('INSERT INTO telemetry(at,operation,provider,model,ms,ok,input_tokens,output_tokens,error) VALUES(?,?,?,?,?,?,?,?,?)',
                   (now(),str(operation)[:50],provider,model,float(ms),int(ok),count(usage.get('prompt_tokens')),count(usage.get('completion_tokens')),str(error)[:60]))
        db.execute('DELETE FROM telemetry WHERE id NOT IN (SELECT id FROM telemetry ORDER BY id DESC LIMIT 2000)')


def metrics():
    with connect() as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM telemetry ORDER BY id DESC LIMIT 200')]
        total=dict(db.execute('SELECT COUNT(*) requests, SUM(ok) successful, AVG(ms) average_ms,SUM(input_tokens) input_tokens,SUM(output_tokens) output_tokens,COUNT(input_tokens) token_measured_requests FROM telemetry').fetchone())
    return {'totals':total,'recent':rows,'scope':'Workspace AI operations only; token totals exclude unreported usage. No cost estimate.'}


def recover():
    # Never restart an in-flight step automatically after process interruption.
    for row in records('plan'):
        plan=row['data'];changed=False
        for step in plan['steps']:
            if step['status']=='running':step['status']='interrupted';changed=True
        if changed or plan['status']=='running':
            plan['status']='paused';plan['message']='Process interrupted. Review the current step, then resume explicitly.'
            save('plan',plan,row['id'])


def memory_context():
    facts=[r['data'] for r in records('fact')][:30]
    goals=[r['data'] for r in records('goal') if r['data'].get('status')!='done'][:15]
    return {'saved_facts':facts,'active_goals':goals}
