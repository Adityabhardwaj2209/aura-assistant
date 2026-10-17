"""Authenticated local UI/API for the virtual body. No motor endpoints."""
import threading
import time
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from aura_body import BODY

ROOT=Path(__file__).resolve().parent


class Engine:
    def __init__(self,body=BODY):
        self.body=body;self.stop_event=threading.Event();self.thread=None
    def start(self):
        if self.thread and self.thread.is_alive():return
        self.stop_event.clear()
        def work():
            while not self.stop_event.wait(.05):
                try:self.body.update()
                except Exception:
                    with self.body.lock:self.body._fault('controller_error')
        self.thread=threading.Thread(target=work,name='aura-virtual-body',daemon=True);self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=1)
        self.body.command('stop')


def install_body(app,require,token):
    @app.get('/body')
    def body_page():
        return HTMLResponse((ROOT/'body_lab.html').read_text(encoding='utf-8').replace('__TOKEN__',token),headers={'Cache-Control':'no-store'})
    @app.get('/body-assets/{name}')
    def body_asset(name:str):
        if name not in ('body_render.js','body_vision.js','body_lab.js','perception_core.js','perception_lab.js','eval_core.js','eval_lab.js','eval_labels.js'):raise HTTPException(404,'Not found')
        return Response((ROOT/name).read_text(encoding='utf-8'),media_type='application/javascript',headers={'Cache-Control':'no-store'})
    @app.get('/api/body/state')
    def body_state(request:Request):
        require(request)
        return BODY.snapshot()
    @app.get('/api/body/history')
    def body_history(request:Request):
        require(request)
        if BODY.recorder is None:return {'events':[],'status':'session-only'}
        try:return {'events':BODY.recorder.recent(),'source':'virtual_simulation'}
        except Exception:raise HTTPException(503,'Body history unavailable; existing database left unchanged') from None
    async def payload(request):
        require(request)
        try:data=await request.json()
        except Exception:raise HTTPException(400,'Expected a JSON object') from None
        if not isinstance(data,dict):raise HTTPException(400,'Expected a JSON object')
        return data
    @app.post('/api/body/heartbeat')
    async def body_heartbeat(request:Request):
        require(request);BODY.heartbeat();return {'ok':True,'simulation_only':True}
    @app.post('/api/body/command')
    async def body_command(request:Request):
        data=await payload(request)
        if set(data)-{'action','params'}:raise HTTPException(400,'Unsupported command fields')
        try:return BODY.command(data.get('action'),data.get('params',{}))
        except (ValueError,TypeError) as error:raise HTTPException(400,str(error)) from None
    @app.post('/api/body/observe')
    async def body_observe(request:Request):
        data=await payload(request)
        try:BODY.observe(data)
        except ValueError as error:raise HTTPException(400,str(error)) from None
        return {'ok':True,'camera_frames_received':False}
    @app.post('/api/body/scene')
    async def body_scene(request:Request):
        data=await payload(request)
        if set(data)!={'obstacles'}:raise HTTPException(400,'Expected obstacles only')
        try:BODY.scene(data['obstacles'])
        except ValueError as error:raise HTTPException(400,str(error)) from None
        return {'ok':True}

    from aura_perception_routes import install_perception
    install_perception(app,require)
    from aura_workspace_routes import install_workspace
    install_workspace(app,require,token)
