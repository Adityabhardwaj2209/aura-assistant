"""Token/origin guarded scene endpoints. Accept boxes, never camera frames."""
from fastapi import HTTPException,Request
from aura_perception import SCENE,sync_head


def install_perception(app,require):
    async def data(request,keys):
        require(request)
        try:packet=await request.json()
        except Exception:raise HTTPException(400,'Expected JSON object') from None
        if not isinstance(packet,dict) or set(packet)!=set(keys):raise HTTPException(400,'Unexpected packet fields; camera frames are not accepted')
        return packet
    def run(fn,*args):
        try:return fn(*args)
        except (ValueError,TypeError) as error:raise HTTPException(400,str(error)) from None
    @app.get('/api/vision/state')
    def state(request:Request):
        require(request);return sync_head()
    @app.post('/api/vision/start')
    async def start(request:Request):
        packet=await data(request,('session','profile'));run(SCENE.start,packet['session'],packet['profile']);return sync_head()
    @app.post('/api/vision/end')
    async def end(request:Request):
        packet=await data(request,('session',));run(SCENE.end,packet['session']);return sync_head()
    @app.post('/api/vision/frame')
    async def frame(request:Request):
        packet=await data(request,('session','profile','seq','age_ms','detections'));run(SCENE.ingest,packet);return sync_head()
    @app.post('/api/vision/target')
    async def target(request:Request):
        packet=await data(request,('selector',));run(SCENE.select,packet['selector']);return sync_head()
    @app.post('/api/vision/release')
    async def release(request:Request):
        await data(request,());SCENE.release();return sync_head()
    @app.post('/api/vision/calibrate')
    async def calibrate(request:Request):
        packet=await data(request,('known_width_m','known_distance_m'))
        return run(SCENE.calibrate,packet['known_width_m'],packet['known_distance_m'])
