"""Persistent structured virtual-task history. Never resumes movement on restart."""
import contextlib
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parent


class WorldMemory:
    def __init__(self,path=None):self.path=Path(path) if path is not None else ROOT/'brain_data'/'body_world.db'
    def connect(self):
        if self.path.is_symlink() or self.path.parent.is_symlink():raise ValueError('Unsafe body-memory path.')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        return sqlite3.connect(self.path,timeout=.3)
    def __call__(self,kind,data):
        if kind not in ('completed_task','scene_updated','fault'):raise ValueError('Unsupported world-memory event.')
        payload=json.dumps(data,ensure_ascii=False,allow_nan=False)
        if len(payload)>6000:raise ValueError('World-memory event is too large.')
        with contextlib.closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS body_events (id INTEGER PRIMARY KEY, recorded TEXT, kind TEXT, payload TEXT)')
            db.execute('INSERT INTO body_events(recorded,kind,payload) VALUES(?,?,?)',(datetime.now(timezone.utc).isoformat(),kind,payload))
            db.execute('DELETE FROM body_events WHERE id NOT IN (SELECT id FROM body_events ORDER BY id DESC LIMIT 300)')
    def recent(self,limit=30):
        if not self.path.exists():return []
        with contextlib.closing(self.connect()) as db:
            rows=db.execute('SELECT recorded,kind,payload FROM body_events ORDER BY id DESC LIMIT ?',(max(1,min(int(limit),100)),)).fetchall()
        return [{'recorded':date,'kind':kind,'data':json.loads(payload),'source':'virtual_simulation'} for date,kind,payload in rows]
