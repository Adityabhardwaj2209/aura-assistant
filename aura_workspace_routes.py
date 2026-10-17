"""Workspace UI/API mounted on the existing loopback server and auth checks."""
import asyncio
import json
import math
import time
from pathlib import Path
from fastapi import Request,HTTPException
from fastapi.responses import HTMLResponse,Response
import aura_workspace_store as store
import aura_workspace_tools as tools
from aura_workspace_ai import complete,local_models
from aura_workspace_planner import create_plan,advance,control

ROOT=Path(__file__).resolve().parent


def install_workspace(app,require,token):
    store.recover()
    semaphore=asyncio.Semaphore(2)
    async def body(request):
        require(request)
        raw=await request.body()
        if len(raw)>500000:raise HTTPException(413,'JSON request too large')
        try:d=json.loads(raw)
        except Exception:raise HTTPException(400,'Expected JSON object') from None
        if not isinstance(d,dict):raise HTTPException(400,'Expected JSON object')
        return d
    async def run_ai(*args,**kwargs):
        async with semaphore:return await complete(*args,**kwargs)
    def settings(d):
        provider=d.get('provider','cloud');model=d.get('model','')
        if not isinstance(model,str) or len(model)>160:raise ValueError('Invalid model')
        return provider,model
    def safe_error(error):
        raise HTTPException(400,str(error)[:600]) from None

    @app.get('/workspace')
    def workspace_page():
        return HTMLResponse((ROOT/'workspace.html').read_text(encoding='utf-8').replace('__TOKEN__',token),headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})

    @app.get('/workspace-assets/{name}')
    def asset(name:str):
        if name not in ('workspace.js','workspace.css','workspace_avatar.js'):raise HTTPException(404,'Not found')
        return Response((ROOT/name).read_bytes(),media_type='text/css' if name.endswith('.css') else 'application/javascript',headers={'Cache-Control':'no-store'})

    @app.get('/api/workspace/state')
    def state(request:Request):
        require(request)
        import aura_brain
        from phase3_web import SETTINGS
        return {'goals':store.records('goal'),'facts':store.records('fact'),'plans':store.records('plan'),'patches':[{**r,'data':{k:v for k,v in r['data'].items() if k not in ('before','candidate')}} for r in store.records('patch')],'documents':aura_brain.documents(),'files':tools.files(),'learning':tools.learning_stats(),'quizzes':[{'id':r['id'],'questions':len(r['data']['questions']),'updated':r['updated']} for r in store.records('quiz')],'metrics':store.metrics(),'evaluations':store.records('evaluation'),'cloud_configured':bool(SETTINGS.get('key')),'system':{'mode':'Software workspace; Phase 4C hardware on hold','file_root':str(tools.FILES),'time':store.now()}}

    @app.post('/api/workspace/record')
    async def record(request:Request):
        d=await body(request)
        try:
            kind=d.get('kind');ident=d.get('id');data=d.get('data')
            if kind not in ('goal','fact'):raise ValueError('Use goals or facts')
            if ident:store.get(ident,kind)
            if not isinstance(data,dict):raise ValueError('Expected data object')
            if kind=='goal':
                status=data.get('status','active')
                if status not in ('active','paused','done'):raise ValueError('Unknown goal status')
                clean={'title':tools.text(data.get('title'),300),'project':tools.text(data.get('project',''),300,False),'next_action':tools.text(data.get('next_action',''),2000,False),'due':tools.text(data.get('due',''),30,False),'status':status}
            else:clean={'name':tools.text(data.get('name'),200),'value':tools.text(data.get('value'),4000)}
            return store.save(kind,clean,ident)
        except (ValueError,TypeError) as e:safe_error(e)

    @app.post('/api/workspace/delete')
    async def delete(request:Request):
        d=await body(request)
        try:
            if d.get('kind') not in ('goal','fact','quiz','attempt','evaluation'):raise ValueError('This record cannot be deleted through this endpoint')
            store.delete(d.get('id'),d['kind']);return {'ok':True}
        except (ValueError,TypeError) as e:safe_error(e)

    @app.get('/api/workspace/export')
    def export(request:Request):
        require(request)
        return {'schema':'aura-workspace-export-v1','at':store.now(),'records':store.records(),'metrics':store.metrics(),'note':'Workspace records only. Chat history, document database and file contents are managed separately.'}

    @app.get('/api/workspace/local-models')
    async def models(request:Request):require(request);return await local_models()

    @app.post('/api/workspace/ask')
    async def ask(request:Request):
        d=await body(request)
        try:return {'answer':await run_ai('assistant',d.get('prompt',''),*settings(d))}
        except (ValueError,TypeError) as e:safe_error(e)

    @app.post('/api/workspace/plan-draft')
    async def plan_draft(request:Request):
        d=await body(request)
        try:
            prompt='Break this task into 3–12 concrete steps. Return ONLY JSON {"steps":["step title"]}. Do not execute anything. Task: '+tools.text(d.get('title'),2000)
            raw=(await run_ai('planning',prompt,*settings(d))).strip()
            if raw.startswith('```'):raw='\n'.join(raw.splitlines()[1:-1])
            draft=json.loads(raw)
            if not isinstance(draft,dict) or not isinstance(draft.get('steps'),list) or not 1<=len(draft['steps'])<=30:raise ValueError('Model returned an invalid plan; enter steps manually')
            return {'steps':[tools.text(s,300) for s in draft['steps']]}
        except (ValueError,TypeError) as e:safe_error(e)

    @app.post('/api/workspace/plan')
    async def plan(request:Request):
        d=await body(request)
        try:return create_plan(d.get('title'),d.get('steps'),d.get('goal_id',''))
        except (ValueError,TypeError) as e:safe_error(e)

    @app.post('/api/workspace/plan-action')
    async def plan_action(request:Request):
        d=await body(request)
        try:
            if d.get('action')=='advance':
                async with semaphore:return await advance(d.get('id'),*settings(d))
            return control(d.get('id'),d.get('action'))
        except (ValueError,TypeError) as e:safe_error(e)

    @app.post('/api/workspace/documents')
    async def docs(request:Request):
        d=await body(request)
        try:
            evidence=tools.doc_evidence(d.get('ids'),tools.text(d.get('query',''),8000,False));mode=d.get('mode','notes')
            if mode=='notes':answer=tools.extractive_notes(evidence)
            elif mode in ('summary','compare'):
                answer=await run_ai('documents',('Compare these selected documents, stating agreements, differences and missing evidence.' if mode=='compare' else 'Summarize these selected document excerpts.')+' User focus: '+d.get('query',''),*settings(d),reference=evidence)
            else:raise ValueError('Unsupported document action')
            return {'answer':answer,'evidence':evidence}
        except (ValueError,TypeError) as e:safe_error(e)

    @app.post('/api/workspace/quiz')
    async def quiz(request:Request):
        d=await body(request)
        try:
            if d.get('import') is not None:data=tools.validate_quiz(d['import'])
            else:
                topic=tools.text(d.get('topic'),300)
                evidence=tools.doc_evidence(d['ids'],topic) if d.get('ids') else None
                prompt='Create 5 practice MCQs about '+topic+'. Return ONLY valid JSON: {"questions":[{"question":"...","options":["A","B","C","D"],"answer":0,"explanation":"...","topic":"..."}]}. answer is 0–3. Explain the answer. These are generated practice questions, not official exam questions.'
                raw=await run_ai('quiz',prompt,*settings(d),reference=evidence)
                raw=raw.strip()
                if raw.startswith('```'):raw='\n'.join(raw.splitlines()[1:-1])
                data=tools.validate_quiz(json.loads(raw))
            return tools.public_quiz(store.save('quiz',data))
        except (ValueError,TypeError) as e:safe_error(e)

    @app.post('/api/workspace/quiz-open')
    async def quiz_open(request:Request):
        d=await body(request)
        try:return tools.public_quiz(store.get(d.get('id'),'quiz'))
        except (ValueError,TypeError) as e:safe_error(e)

    @app.post('/api/workspace/grade')
    async def grade(request:Request):
        d=await body(request)
        try:return tools.grade(d.get('id'),d.get('answers'))
        except (ValueError,TypeError) as e:safe_error(e)

    @app.post('/api/workspace/file')
    async def file(request:Request):
        d=await body(request)
        try:
            if d.get('action')=='read':return {'text':tools.read_file(d.get('name'))}
            if d.get('action')=='write':return tools.write_file(d.get('name'),d.get('text'))
            raise ValueError('Unknown file action')
        except (ValueError,TypeError,OSError,UnicodeError) as e:safe_error(e)

    @app.post('/api/workspace/app')
    async def app_open(request:Request):
        d=await body(request)
        try:return tools.open_app(d.get('app'))
        except (ValueError,TypeError,OSError) as e:safe_error(e)

    @app.post('/api/workspace/code')
    async def code(request:Request):
        d=await body(request)
        try:
            action=d.get('action')
            if action=='check':return tools.validate_python(d.get('source'))
            if action=='tests':
                from aura_workspace_test_runner import run_reviewed
                async with semaphore:return await asyncio.to_thread(run_reviewed,d.get('source'),d.get('tests'),d.get('reviewed',False))
            if action=='propose':return tools.propose_patch(d.get('file'),d.get('candidate'))
            if action in ('apply','rollback'):return tools.patch_action(d.get('id'),action)
            if action=='diagnose':
                source=tools.read_file(d.get('file'))
                return {'answer':await run_ai('coding','Diagnose this Python file. Explain bugs, suggest a minimal patch and tests. Do not claim to run code. Error report: '+tools.text(d.get('error','No error supplied'),8000),*settings(d),reference={'file':d.get('file'),'source':source[:50000],'syntax_check':tools.validate_python(source)})}
            raise ValueError('Unknown coding action')
        except (ValueError,TypeError,OSError) as e:safe_error(e)

    @app.post('/api/workspace/screen')
    async def screen(request:Request):
        require(request)
        form=await request.form();file=form.get('file')
        if not file or not hasattr(file,'read'):raise HTTPException(400,'Choose a screenshot')
        raw=await file.read(4_000_001)
        if len(raw)>4_000_000:raise HTTPException(413,'Screenshot must be below 4 MB')
        if raw.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
        elif raw.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
        else:raise HTTPException(400,'Only PNG/JPEG screenshots')
        try:
            return {'answer':await run_ai('screen',str(form.get('prompt') or 'Explain this screenshot and visible errors.'),'cloud',str(form.get('model') or 'qwen/qwen3.8-27b'),image=(mime,raw)),'image_saved':False}
        except (ValueError,TypeError) as e:safe_error(e)
        finally:await file.close()

    @app.post('/api/workspace/evaluation')
    async def evaluation(request:Request):
        d=await body(request)
        try:
            # Extract known metrics only. Never execute report data or infer unmeasured accuracy.
            name=tools.text(d.get('name'),120);report=d.get('report')
            if not isinstance(report,dict):raise ValueError('Expected report JSON')
            from aura_workspace_evaluation import extract_evaluation
            return store.save('evaluation',{'name':name,**extract_evaluation(report)})
        except (ValueError,TypeError) as e:safe_error(e)

    @app.post('/api/workspace/speak')
    async def speak(request:Request):
        d=await body(request)
        try:
            from aura_workspace_voice import synthesize
            async with semaphore:return await asyncio.to_thread(synthesize,d.get('text'),d.get('voice',''))
        except Exception as e:
            if isinstance(e,(ValueError,TypeError)):safe_error(e)
            raise HTTPException(503,'Windows speech unavailable. Use an installed System.Speech voice; avatar gestures still work.') from None
