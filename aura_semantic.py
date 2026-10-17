"""Local multilingual vectors + existing keyword retrieval."""
import argparse
import hashlib
import json
import math
import sqlite3
import threading
import warnings
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
_MODEL = None
_LOCK = threading.RLock()
_WARNED = False


@contextmanager
def database():
    import aura_brain as brain
    brain.initialize()
    db = sqlite3.connect(brain.DB, timeout=30)
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS semantic_vectors (pid INTEGER, digest TEXT NOT NULL, part INTEGER, model TEXT NOT NULL, vector BLOB NOT NULL, PRIMARY KEY(pid,part,model))')
            db.execute('CREATE TABLE IF NOT EXISTS semantic_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            yield db
    finally:
        db.close()


def fingerprint(doc_id, page, text):
    return hashlib.sha256(json.dumps([doc_id,page,text],ensure_ascii=False).encode()).hexdigest()


def passages():
    with database() as db:
        return db.execute('SELECT p.rowid,p.doc_id,p.page,p.text,d.name FROM passages p JOIN documents d ON d.id=p.doc_id ORDER BY p.rowid').fetchall()


def model():
    global _MODEL
    with _LOCK:
        if _MODEL is None:
            from fastembed import TextEmbedding
            _MODEL = TextEmbedding(model_name=MODEL, cache_dir=str(ROOT/'brain_data'/'embedding_models'), threads=2)
        return _MODEL


def normalized(vector):
    import numpy as np
    value = np.asarray(vector,dtype=np.float32).reshape(-1)
    size = float(np.linalg.norm(value))
    if not value.size or not np.isfinite(value).all() or not math.isfinite(size) or size<=0:
        raise ValueError('Invalid embedding received.')
    return value/size


def segments(text):
    # Keep segments small for this model's short context; overlap limits loss
    # at boundaries. Exact token counts vary by language/tokenizer.
    return [text[start:start+320] for start in range(0,len(text),260)]


def reindex():
    import numpy as np
    rows = passages()
    if not rows:
        return {'indexed_passages':0,'message':'Import a document first.'}
    engine = model()
    # The database remains intact if model download or vector generation fails.
    prepared = []
    for pid,doc_id,page,text,name in rows:
        pieces = segments(text)
        with _LOCK:
            vectors = list(engine.embed(pieces, batch_size=16))
        if len(vectors)!=len(pieces):
            raise ValueError('Embedding count does not match passages.')
        digest = fingerprint(doc_id,page,text)
        for part,value in enumerate(vectors):
            prepared.append((pid,digest,part,MODEL,normalized(value).astype('<f4').tobytes()))
        print('Indexed: '+name+' • page '+str(page),flush=True)
    # Replace this model's index atomically. New docs added during indexing
    # are simply reported as not yet indexed and still searchable by keyword.
    with database() as db:
        db.execute('DELETE FROM semantic_vectors WHERE model=?',(MODEL,))
        db.executemany('INSERT INTO semantic_vectors(pid,digest,part,model,vector) VALUES(?,?,?,?,?)',prepared)
        db.execute('INSERT INTO semantic_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('enabled_model',MODEL))
    return {'indexed_passages':len(rows),'vectors':len(prepared),'model':MODEL}


def status():
    rows=passages()
    live={pid:fingerprint(doc_id,page,text) for pid,doc_id,page,text,name in rows}
    with database() as db:
        enabled=db.execute("SELECT value FROM semantic_state WHERE key='enabled_model'").fetchone()
        indexed={pid for pid,digest in db.execute('SELECT DISTINCT pid,digest FROM semantic_vectors WHERE model=?',(MODEL,)) if live.get(pid)==digest}
    return {'enabled':bool(enabled and enabled[0]==MODEL),'passages':len(rows),'indexed_passages':len(indexed),'pending_passages':len(rows)-len(indexed),'model':MODEL}


def semantic_search(query,limit=8,minimum=.35):
    import numpy as np
    live={pid:(doc_id,int(page),text,name) for pid,doc_id,page,text,name in passages()}
    with database() as db:
        stored=db.execute('SELECT pid,digest,vector FROM semantic_vectors WHERE model=?',(MODEL,)).fetchall()
    valid=[]
    for pid,digest,blob in stored:
        item=live.get(pid)
        if item and fingerprint(item[0],item[1],item[2])==digest:
            valid.append((pid,np.frombuffer(blob,dtype='<f4')))
    if not valid:
        return []
    with _LOCK:
        q=normalized(next(iter(model().embed([query],batch_size=1))))
    best={}
    for pid,value in valid:
        if value.shape!=q.shape:
            continue
        score=float(np.dot(q,value))
        if score>=minimum and score>best.get(pid,-1):
            best[pid]=score
    out=[]
    for pid,score in sorted(best.items(),key=lambda pair:pair[1],reverse=True)[:limit]:
        _,page,text,name=live[pid]
        out.append({'source':name,'page':page,'text':text,'semantic_score':round(score,4)})
    return out


def hybrid_search(query,keyword_search,limit=4):
    global _WARNED
    if not query.strip():
        return []
    limit=max(1,min(int(limit),8))
    lexical=keyword_search(query,8)
    try:
        with database() as db:
            enabled=db.execute("SELECT value FROM semantic_state WHERE key='enabled_model'").fetchone()
        if not enabled or enabled[0]!=MODEL:
            return lexical[:limit]
        semantic=semantic_search(query,8)
    except Exception as error:
        if not _WARNED:
            warnings.warn('AURA semantic search unavailable; using keyword search. Error type: '+type(error).__name__,RuntimeWarning)
            _WARNED=True
        return lexical[:limit]
    scores={};items={}
    # Reciprocal-rank fusion: keyword and semantic scores have different scales.
    for results in [lexical,semantic]:
        for rank,item in enumerate(results,1):
            key=(item['source'],item['page'],item['text'])
            scores[key]=scores.get(key,0)+1/(60+rank)
            items[key]=item
    return [items[key] for key in sorted(scores,key=scores.get,reverse=True)[:limit]]


def self_test():
    engine=model()
    questions=['An automobile needs petrol.','A car requires fuel.','Bananas are yellow fruit.']
    with _LOCK:
        vectors=[normalized(x) for x in engine.embed(questions,batch_size=3)]
    related=float(vectors[0]@vectors[1]);other=float(vectors[0]@vectors[2])
    if related<=other:
        raise ValueError('Semantic smoke test failed: related sentences did not rank first.')
    return {'related_similarity':round(related,4),'unrelated_similarity':round(other,4),'result':'PASS'}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--reindex',action='store_true')
    parser.add_argument('--status',action='store_true')
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--search')
    args=parser.parse_args()
    try:
        if args.reindex:result=reindex()
        elif args.self_test:result=self_test()
        elif args.search:
            import aura_brain
            result=aura_brain.search(args.search)
        else:result=status()
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as error:
        print('Semantic operation failed ('+type(error).__name__+'): '+str(error))
        raise SystemExit(1)
