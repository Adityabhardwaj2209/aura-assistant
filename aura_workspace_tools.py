"""Local bounded tools. No arbitrary shell execution or automatic code execution."""
from pathlib import Path
import ast
import difflib
import hashlib
import os
import re
import subprocess
import sys
import threading
import uuid
from aura_workspace_store import ROOT, save, get, records

FILES=ROOT/'workspace_files'
LOCK=threading.RLock()
APPS={'notepad':'notepad.exe','calculator':'calc.exe'}


def text(value,limit=8000,required=True):
    if not isinstance(value,str) or len(value)>limit or (required and not value.strip()):raise ValueError('Invalid or oversized text')
    return value


def safe_path(name):
    name=text(name,180)
    if '\\' in name or ':' in name or name.startswith('/') or any(p in ('','..','.') for p in name.split('/')):raise ValueError('Use a relative filename within workspace_files')
    parts=name.split('/')
    if any(not re.fullmatch(r'[A-Za-z0-9_ .-]+',p) or p.endswith((' ','.')) or p.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))} for p in parts):raise ValueError('Unsupported filename')
    FILES.mkdir(parents=True,exist_ok=True)
    if FILES.is_symlink() or (hasattr(FILES,'is_junction') and FILES.is_junction()):raise ValueError('Workspace root cannot be a link')
    path=FILES
    for part in parts:
        path=path/part
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):raise ValueError('Linked paths are not allowed')
    if not path.resolve().is_relative_to(FILES.resolve()):raise ValueError('Outside approved workspace')
    return path


def write_file(name,content,overwrite=False):
    content=text(content,100000,False)
    with LOCK:
        path=safe_path(name)
        if path.suffix.lower() not in {'.txt','.md','.json','.py','.csv'}:raise ValueError('Allowed files: TXT MD JSON PY CSV')
        if path.exists() and not overwrite:raise ValueError('File exists; choose a new filename or use reviewed patch')
        path.parent.mkdir(parents=True,exist_ok=True)
        if overwrite:
            temporary=path.with_name(path.name+'.aura_tmp_'+uuid.uuid4().hex)
            try:
                with temporary.open('x',encoding='utf-8') as file:file.write(content)
                temporary.replace(path)
            finally:temporary.unlink(missing_ok=True)
        else:
            with path.open('x',encoding='utf-8') as file:file.write(content)
    return {'file':str(path.relative_to(FILES)),'characters':len(content)}


def read_file(name):
    path=safe_path(name)
    if not path.is_file() or path.stat().st_size>150000:raise ValueError('Choose an existing text file below 150 KB')
    return path.read_text(encoding='utf-8-sig')


def files():
    FILES.mkdir(parents=True,exist_ok=True)
    result=[]
    # Do not traverse directory links or Windows junctions.
    for root,dirs,names in os.walk(FILES,followlinks=False):
        dirs[:]=[d for d in dirs if not (Path(root)/d).is_symlink() and not (hasattr(Path(root)/d,'is_junction') and (Path(root)/d).is_junction())]
        for name in names:
            try:
                path=Path(root)/name
                if path.is_symlink():continue
                result.append({'name':str(path.relative_to(FILES)).replace('\\','/'),'bytes':path.stat().st_size})
            except OSError:continue
            if len(result)>=300:return result
    return result


def open_app(app):
    if app not in APPS:raise ValueError('Only Notepad and Calculator are allowed')
    if sys.platform!='win32':raise ValueError('Desktop app launch is Windows only')
    # Fixed absolute executable, never a user-supplied command or shell string.
    exe=Path(os.environ.get('SystemRoot','C:\\Windows'))/'System32'/APPS[app]
    subprocess.Popen([str(exe)],shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return {'opened':app}


def validate_python(source):
    source=text(source,100000,False)
    import tempfile
    with tempfile.TemporaryDirectory(prefix='aura_code_check_') as folder:
        p=Path(folder)/'candidate.py';p.write_text(source,encoding='utf-8')
        try:
            tree=ast.parse(p.read_text(encoding='utf-8'),filename='candidate.py')
            compile(tree,'candidate.py','exec') # Compile only. Never exec/eval/import candidate code.
        except SyntaxError as e:return {'ok':False,'line':e.lineno,'message':e.msg,'scope':'Python syntax only; code was not executed'}
    return {'ok':True,'scope':'Python syntax only; code was not executed'}


def digest(source):return hashlib.sha256(source.encode('utf-8')).hexdigest()


def propose_patch(name,candidate):
    candidate=text(candidate,100000,False)
    original=read_file(name)
    if not name.lower().endswith('.py'):raise ValueError('Reviewed patch currently supports Python files only')
    check=validate_python(candidate)
    diff=''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile=name,tofile=name+' (proposed)'))
    return save('patch',{'file':name,'before':original,'candidate':candidate,'base_hash':digest(original),'candidate_hash':digest(candidate),'diff':diff,'check':check,'status':'proposed'})


def patch_action(ident,action):
    with LOCK:
        row=get(ident,'patch');p=row['data'];current=read_file(p['file'])
        if action=='apply':
            if p['status']!='proposed' or not p['check']['ok']:raise ValueError('Only a syntax-valid proposed patch can be applied')
            if digest(current)!=p['base_hash']:raise ValueError('File changed; create a new patch')
            write_file(p['file'],p['candidate'],True);p['status']='applied'
        elif action=='rollback':
            if p['status']!='applied' or digest(current)!=p['candidate_hash']:raise ValueError('Rollback blocked: file changed since patch')
            write_file(p['file'],p['before'],True);p['status']='rolled_back'
        else:raise ValueError('Unknown patch action')
        try:return save('patch',p,ident)
        except Exception:
            write_file(p['file'],current,True)
            raise


def doc_evidence(ids,query=''):
    import aura_brain as brain
    if not isinstance(ids,list) or not 1<=len(ids)<=6 or any(type(i)!=int for i in ids):raise ValueError('Select 1–6 documents')
    brain.initialize();out=[]
    query=text(query,8000,False)
    tokens=set(re.findall(r'\w+',query.lower()))
    with brain.connect() as db:
        for ident in dict.fromkeys(ids):
            row=db.execute('SELECT name,pages FROM documents WHERE id=?',(ident,)).fetchone()
            if not row:raise ValueError('Selected document no longer exists')
            chunks=db.execute('SELECT rowid,page,text FROM passages WHERE doc_id=? ORDER BY rowid',(ident,)).fetchall()
            if tokens:
                chunks=sorted(chunks,key=lambda c:-sum(t in c[2].lower() for t in tokens))
            chosen=chunks[:5]
            out.append({'id':ident,'name':row[0],'pages':row[1],'total_chunks':len(chunks),'selected_chunks':len(chosen),'coverage':'Selected excerpts only; not a complete-document review','excerpts':[{'citation':f'[{row[0]}, p.{c[1]}]','page':int(c[1]),'text':c[2]} for c in chosen]})
    return out


def extractive_notes(evidence):
    return '\n\n'.join(d['name']+' — '+d['coverage']+'\n'+'\n'.join(e['citation']+' '+e['text'][:800] for e in d['excerpts']) for d in evidence)


def validate_quiz(data):
    if not isinstance(data,dict) or not isinstance(data.get('questions'),list) or not 1<=len(data['questions'])<=10:raise ValueError('Quiz must contain 1–10 questions')
    clean=[]
    for q in data['questions']:
        if not isinstance(q,dict) or not isinstance(q.get('options'),list) or len(q['options'])!=4 or type(q.get('answer'))!=int or q['answer'] not in range(4):raise ValueError('Each question needs four choices and answer index 0–3')
        clean.append({'question':text(q.get('question'),2000),'options':[text(o,800) for o in q['options']],'answer':q['answer'],'explanation':text(q.get('explanation'),3000),'topic':text(q.get('topic','General'),200)})
    return {'questions':clean}


def public_quiz(row):
    return dict(id=row['id'],questions=[{k:v for k,v in q.items() if k not in ('answer','explanation')} for q in row['data']['questions']])


def grade(ident,answers):
    q=get(ident,'quiz')['data']['questions']
    if not isinstance(answers,list) or len(answers)!=len(q) or any(type(a)!=int or a not in range(4) for a in answers):raise ValueError('Answer every question')
    rows=[dict(topic=x['topic'],correct=a==x['answer'],answer=x['answer'],explanation=x['explanation']) for x,a in zip(q,answers)]
    return save('attempt',{'quiz':ident,'score':sum(x['correct'] for x in rows),'total':len(rows),'results':rows})


def learning_stats():
    topics={}
    for attempt in records('attempt'):
        for result in attempt['data']['results']:
            t=topics.setdefault(result['topic'],{'answered':0,'correct':0});t['answered']+=1;t['correct']+=int(result['correct'])
    return [{'topic':k,**v,'accuracy':v['correct']/v['answered'],'practice_priority':v['correct']/v['answered']<.7} for k,v in sorted(topics.items())]
