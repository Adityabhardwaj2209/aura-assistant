"""Bounded, checkpointed task executor. One step per explicit advance/resume."""
import asyncio
import json
import threading
from aura_workspace_store import save,get,records
from aura_workspace_tools import text,write_file,doc_evidence,extractive_notes

LOCK=threading.RLock()
INFLIGHT=set()
ACTIONS={'manual','notes','ai','write'}


def create_plan(title,steps,goal_id=''):
    title=text(title,300)
    if goal_id:get(goal_id,'goal')
    if not isinstance(steps,list) or not 1<=len(steps)<=30:raise ValueError('Use 1–30 steps')
    clean=[]
    for step in steps:
        if not isinstance(step,dict) or step.get('action') not in ACTIONS:raise ValueError('Unknown step action')
        action=step['action'];params=step.get('params',{})
        if not isinstance(params,dict):raise ValueError('Step params must be an object')
        if action=='write':
            from aura_workspace_tools import safe_path
            safe_path(params.get('file',''));text(params.get('content',''),100000,False)
        if action=='notes':
            ids=params.get('documents')
            if not isinstance(ids,list) or not ids or any(type(i)!=int for i in ids):raise ValueError('Notes step needs document ids')
        if action=='ai':text(params.get('prompt',''),16000)
        clean.append({'title':text(step.get('title',''),300),'action':action,'params':params,'status':'pending','result':''})
    return save('plan',{'title':title,'goal_id':goal_id,'steps':clean,'status':'paused','message':'Review steps; advance runs one step only.'})


async def advance(ident,provider='cloud',model=''):
    from aura_workspace_ai import complete
    with LOCK:
        if ident in INFLIGHT:raise ValueError('This plan already has a running step')
        row=get(ident,'plan');plan=row['data']
        if plan['status']=='done':return row
        index=next((i for i,s in enumerate(plan['steps']) if s['status']!='done'),None)
        if index is None:plan['status']='done';return save('plan',plan,ident)
        step=plan['steps'][index]
        if step['status'] in ('failed','interrupted'):raise ValueError('Review the failed/interrupted step, then choose Retry step')
        if step['action']=='manual':
            step['status']='waiting';plan['status']='paused';plan['message']='Complete this manual step yourself, then mark it done.'
            return save('plan',plan,ident)
        step['status']='running';plan['status']='running';plan['message']='Running step '+str(index+1)
        save('plan',plan,ident);INFLIGHT.add(ident)
    try:
        p=step['params']
        if step['action']=='notes':result=await asyncio.to_thread(lambda:extractive_notes(doc_evidence(p['documents'],p.get('query',''))))
        elif step['action']=='write':result=json.dumps(await asyncio.to_thread(write_file,p['file'],p['content']))
        elif step['action']=='ai':result=await complete('planner',p['prompt'],provider,model,{'previous_step_results':[s['result'][:5000] for s in plan['steps'][:index]]})
        with LOCK:
            current=get(ident,'plan')['data'];current['steps'][index].update(status='done',result=result[:40000])
            complete_all=all(s['status']=='done' for s in current['steps'])
            current['status']='done' if complete_all else 'paused';current['message']='Step saved. Advance when ready.'
            return save('plan',current,ident)
    except BaseException as error:
        with LOCK:
            current=get(ident,'plan')['data'];current['steps'][index].update(status='interrupted' if isinstance(error,asyncio.CancelledError) else 'failed',result='Step failed. Review external effects before retry. '+str(error)[:500])
            current['status']='paused';save('plan',current,ident)
        raise
    finally:
        with LOCK:INFLIGHT.discard(ident)


def control(ident,action):
    with LOCK:
        if ident in INFLIGHT:raise ValueError('Wait for the current bounded step to finish; next step never starts automatically')
        row=get(ident,'plan');plan=row['data'];step=next((s for s in plan['steps'] if s['status']!='done'),None)
        if action=='retry':
            if not step or step['status'] not in ('failed','interrupted'):raise ValueError('No failed/interrupted step')
            step.update(status='pending',result='')
        elif action=='resolve':
            if not step or step['status'] not in ('failed','interrupted'):raise ValueError('No failed/interrupted step to reconcile')
            step.update(status='done',result='User reviewed external effects and marked this step resolved')
        elif action=='confirm':
            if not step or step['status']!='waiting' or step['action']!='manual':raise ValueError('No waiting manual step')
            step.update(status='done',result='Marked complete by user')
        else:raise ValueError('Unknown plan action')
        plan['status']='done' if all(s['status']=='done' for s in plan['steps']) else 'paused'
        return save('plan',plan,ident)
