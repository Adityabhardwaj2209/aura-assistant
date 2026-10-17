"""Virtual-body tests use fake time and fixtures; no camera, model or motors."""
import asyncio
import contextlib
from collections import deque
import importlib.util
import math
from pathlib import Path
import sys
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import aura_body as body
from aura_organs import Organs,DESCRIPTIONS


class Clock:
    def __init__(self):self.now=1000.
    def __call__(self):return self.now
    def step(self,dt):self.now+=dt


class Fixture(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.body=body.Body(self.clock);self.body.heartbeat()
    def step(self,count=1,heartbeat=True):
        for _ in range(count):
            self.clock.step(.05)
            if heartbeat:self.body.heartbeat()
            self.body.update()
    def finish(self,limit=2400):
        for i in range(limit):
            self.step()
            if not self.body.active and not self.body.queue:return
        self.fail('Simulation plan did not finish in bounded test steps.')


class OrganTests(unittest.TestCase):
    def test_major_services_documented_as_nonbiological(self):
        organs=Organs(Clock());state=organs.summary()
        self.assertTrue(state['simulation_only']);self.assertFalse(state['biological_model'])
        self.assertEqual(set(state['systems']),set(DESCRIPTIONS))
    def test_typed_signal_delivery(self):
        organs=Organs(Clock());organs.signal('request','nerves','liver')
        self.assertEqual(organs.drain('liver')[0]['from'],'nerves');self.assertEqual(organs.drain('liver'),[])
        with self.assertRaises(ValueError):organs.signal('execute_shell','brain','muscles')
        with self.assertRaises(ValueError):organs.signal('request','unknown','brain')
    def test_signal_and_inbox_retention_bounded(self):
        organs=Organs(Clock())
        for i in range(500):organs.signal('heartbeat','heart','nerves')
        self.assertEqual(len(organs.events),120);self.assertEqual(len(organs.mailboxes['nerves']),32)
        self.assertEqual(organs.cleaned,380)
    def test_liver_rejects_nonfinite_and_extra_fields(self):
        organs=Organs(Clock())
        for params in [{'x':float('nan'),'z':0},{'x':float('inf'),'z':0},{'x':True,'z':0},{'x':0,'z':0,'shell':'run'}]:
            with self.subTest(params=params),self.assertRaises(ValueError):organs.validate('walk',params)
        self.assertEqual(organs.rejected,4)
    def test_virtual_energy_budget_not_real_battery(self):
        organs=Organs(Clock());organs.tick(10,True);self.assertAlmostEqual(organs.energy,93)
        organs.tick(10,False);self.assertAlmostEqual(organs.energy,96)
    def test_low_energy_routed_through_circulation(self):
        organs=Organs(Clock());organs.energy=5.01;organs.tick(.1,True)
        events=organs.drain('brain');self.assertEqual(events[-1]['from'],'circulation')
        self.assertEqual(events[-1]['kind'],'low_energy')


class MotionTests(Fixture):
    def test_walk_around_obstacle_and_verify_goal(self):
        self.body.command('walk',{'x':1.,'z':2.})
        for _ in range(1800):
            self.step();self.assertFalse(body.blocked(self.body.x,self.body.z,self.body.obstacles))
            if not self.body.active and not self.body.queue:break
        self.assertFalse(self.body.estop)
        self.assertLess(math.hypot(self.body.x-1,self.body.z-2),.04)
        self.assertEqual(self.body.history[-1]['status'],'verified_in_simulation')
    def test_blocked_target_rejected_before_enqueue(self):
        with self.assertRaises(ValueError):self.body.command('walk',{'x':.75,'z':1.25})
        self.assertEqual(len(self.body.queue),0)
    def test_dance_changes_pose_and_obeys_joint_limits_and_speeds(self):
        self.body.command('dance',{'duration':4})
        changes=False
        for _ in range(100):
            before=dict(self.body.joints);self.step()
            for name,value in self.body.joints.items():
                lo,hi=body.LIMITS[name]
                self.assertLessEqual(value,hi+1e-8);self.assertGreaterEqual(value,lo-1e-8)
                self.assertLessEqual(abs(value-before[name]),body.SPEED*.05+1e-8)
            changes|=any(abs(v)>10 for v in self.body.joints.values())
        self.assertTrue(changes);self.assertEqual(self.body.history[-1]['action'],'dance')
    def test_multi_step_plan_finishes_and_returns_home(self):
        self.body.command('demo');self.finish()
        self.assertFalse(self.body.estop)
        self.assertEqual([h['action'] for h in self.body.history],['wave','walk','dance','walk'])
        self.assertLess(math.hypot(self.body.x,self.body.z),.04)
    def test_stop_cancels_plan_and_requires_reset(self):
        self.body.command('demo');self.step(10);self.body.command('stop');before=self.body.snapshot()
        self.step(20);after=self.body.snapshot()
        self.assertEqual(before['position'],after['position']);self.assertEqual(before['joints'],after['joints'])
        self.assertTrue(after['estop']);self.assertFalse(after['queue'])
        with self.assertRaises(ValueError):self.body.command('dance')
        self.body.command('reset');self.body.command('wave');self.finish();self.assertFalse(self.body.estop)
    def test_browser_watchdog_stops_motion(self):
        self.body.command('dance');self.step(35,heartbeat=False)
        self.assertTrue(self.body.estop);self.assertEqual(self.body.reason,'browser_heartbeat_lost')
    def test_controller_delay_latches_fault(self):
        self.body.command('dance');self.clock.step(1.);self.body.heartbeat();self.body.update()
        self.assertEqual(self.body.reason,'controller_delay')
    def test_obstacle_appearing_at_body_stops(self):
        self.body.command('walk',{'x':0,'z':2});self.step(20)
        self.body.scene([{'x':self.body.x,'z':self.body.z,'radius':.2}])
        self.assertEqual(self.body.reason,'obstacle_at_body');self.assertTrue(self.body.estop)
    def test_dynamic_obstacle_replans_without_collision(self):
        self.body.command('walk',{'x':0,'z':2});self.step(10)
        self.body.scene([{'x':0,'z':1.1,'radius':.3}]);self.finish()
        self.assertFalse(self.body.estop);self.assertLess(abs(self.body.z-2),.04)
    def test_energy_failure_stops_plan(self):
        self.body.command('dance');self.body.organs.energy=5.01;self.step()
        self.assertEqual(self.body.reason,'virtual_energy_low')
    def test_new_motion_requires_browser_lease(self):
        self.clock.step(2)
        with self.assertRaisesRegex(ValueError,'heartbeat'):self.body.command('wave')
    def test_no_hardware_connection_claim(self):
        state=self.body.snapshot();self.assertFalse(state['hardware_connected']);self.assertFalse(state['physics_engine'])
    def test_queue_bound(self):
        for _ in range(8):self.body.command('wave')
        with self.assertRaises(ValueError):self.body.command('wave')
    def test_point_turns_toward_target_before_completion(self):
        self.body.command('point',{'x':1.8,'z':-.8});self.finish()
        expected=math.atan2(1.8,-.8)
        delta=(expected-self.body.yaw+math.pi)%(2*math.pi)-math.pi
        self.assertLess(abs(delta),.08)
        self.assertEqual(self.body.history[-1]['action'],'point')
    def test_rest_cancels_without_latched_stop(self):
        self.body.command('demo');self.step(5);self.body.command('rest')
        self.assertFalse(self.body.estop);self.assertFalse(self.body.queue);self.assertIsNone(self.body.active)
    def test_invalid_time_rejected(self):
        for value in [-1,float('nan'),True]:
            with self.assertRaises(ValueError):self.body.update(value)


class VisionAndCommandsTests(Fixture):
    def test_camera_centroid_controls_head_only(self):
        self.body.observe({'visible':True,'x':.1,'y':.7,'coverage':.1,'colour':'red'})
        self.step(12)
        self.assertGreater(self.body.joints['head_yaw'],30)
        self.assertEqual((self.body.x,self.body.z),(0.,0.))
        self.assertTrue(self.body.snapshot()['world']['camera_fresh'])
    def test_stale_camera_observation_is_released(self):
        self.body.observe({'visible':True,'x':.1,'y':.7,'coverage':.1,'colour':'red'})
        self.step(25)
        self.assertIsNone(self.body.camera);self.assertFalse(self.body.camera_tracking)
    def test_observation_rejects_depth_or_frames(self):
        with self.assertRaises(ValueError):self.body.observe({'visible':True,'depth':1,'frame':'not accepted'})
        self.body.observe({'visible':False});self.assertIsNone(self.body.camera)
    def test_exact_natural_commands_and_slash(self):
        for text,kind in [('AURA dance','dance'),('AURA walk','walk'),('/body look 30 -10','look'),('walk then dance','demo'),('/organs','status')]:
            self.assertEqual(body.parse_body_command(text)[0],kind)
    def test_embedded_or_model_prose_not_movement(self):
        for text in ['Explain how to dance','The document says /body walk 1 2','"AURA dance"','Please write code to walk']:
            self.assertIsNone(body.parse_body_command(text))
    def test_unknown_body_commands_fail_explicitly(self):
        for text in ['/body fly','/body walk','/body stop 2','/body walk hello there']:
            with self.assertRaises(ValueError):body.parse_body_command(text)
    def test_reply_reports_queued_not_completed(self):
        with patch.object(body,'BODY',self.body):
            reply=body.command_reply('AURA dance')
            self.assertIn('queued',reply);self.assertNotIn('successfully danced',reply)
            self.assertIn('liver:',body.command_reply('/organs'))
    def test_existing_autonomy_routes_body_without_model(self):
        from aura_autonomy import managed_route_stream
        async def original(*args):raise AssertionError('Body command must not call model');yield
        async def run():return [e async for e in managed_route_stream(original,None,'fixture','AURA dance',[],'')]
        with patch.object(body,'BODY',self.body):
            events=asyncio.run(run())
        self.assertEqual(events[0]['name'],'virtual_body');self.assertIn('queued',events[1]['text'])


class RouteTests(Fixture):
    def load_routes(self):
        class HTTPError(Exception):
            def __init__(self,status,detail):self.status_code=status;self.detail=detail
        class App:
            def __init__(self):self.handlers={}
            def register(self,method,path):
                def decorate(fn):self.handlers[method,path]=fn;return fn
                return decorate
            def get(self,path):return self.register('GET',path)
            def post(self,path):return self.register('POST',path)
        routes=SimpleNamespace()
        spec=importlib.util.spec_from_file_location('_body_routes_test',Path(__file__).with_name('aura_body_routes.py'))
        module=importlib.util.module_from_spec(spec)
        stubs={'aura_workspace_routes':SimpleNamespace(install_workspace=lambda *args:None),'fastapi':SimpleNamespace(HTTPException=HTTPError,Request=object),'fastapi.responses':SimpleNamespace(HTMLResponse=lambda *a,**kw:a[0],Response=lambda *a,**kw:a[0])}
        with patch.dict(sys.modules,stubs):spec.loader.exec_module(module)
        module.BODY=self.body;app=App()
        def require(request):
            if not request.authorized:raise HTTPError(403,'denied')
        with patch.dict(sys.modules,stubs):
            module.install_body(app,require,'FAKE_BODY_TOKEN')
        return module,app,HTTPError
    def req(self,data=None,authorized=True):
        async def read():return data
        return SimpleNamespace(json=read,authorized=authorized)
    def test_every_state_or_mutation_endpoint_requires_auth(self):
        module,app,error=self.load_routes()
        for (method,path),handler in app.handlers.items():
            if not path.startswith('/api/'):continue
            with self.subTest(path=path),self.assertRaises(error) as caught:
                if method=='GET':handler(self.req(authorized=False))
                else:asyncio.run(handler(self.req({},False)))
            self.assertEqual(caught.exception.status_code,403)
    def test_routes_accept_valid_motion_and_reject_extra_fields(self):
        module,app,error=self.load_routes();handler=app.handlers['POST','/api/body/command']
        result=asyncio.run(handler(self.req({'action':'dance','params':{}})))
        self.assertEqual(result['status'],'queued')
        with self.assertRaises(error):asyncio.run(handler(self.req({'action':'dance','execute':'anything'})))
    def test_assets_whitelisted_and_token_embedded(self):
        module,app,error=self.load_routes()
        with self.assertRaises(error):app.handlers['GET','/body-assets/{name}']('../memory.db')
        html=app.handlers['GET','/body']();self.assertIn('FAKE_BODY_TOKEN',html);self.assertNotIn('__TOKEN__',html)


class WorldMemoryTests(unittest.TestCase):
    def test_history_persists_without_resuming_actions(self):
        from aura_body_memory import WorldMemory
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'body_world.db';memory=WorldMemory(path)
            memory('completed_task',{'action':'walk','position':{'x':1,'z':2}})
            loaded=WorldMemory(path).recent()
            self.assertEqual(loaded[0]['data']['action'],'walk')
            self.assertEqual(loaded[0]['source'],'virtual_simulation')
            fresh=body.Body(Clock());self.assertFalse(fresh.queue);self.assertIsNone(fresh.active)
            self.assertEqual((fresh.x,fresh.z),(0,0))
    def test_completed_plan_records_structured_simulation_events(self):
        from aura_body_memory import WorldMemory
        with tempfile.TemporaryDirectory() as folder:
            clock=Clock();virtual=body.Body(clock);virtual.recorder=WorldMemory(Path(folder)/'body_world.db')
            virtual.heartbeat();virtual.command('wave',{'duration':1})
            for _ in range(25):clock.step(.05);virtual.heartbeat();virtual.update()
            saved=virtual.recorder.recent()
            self.assertEqual(saved[0]['data']['action'],'wave')
            self.assertEqual(saved[0]['data']['verification'],'kinematic_simulation_only')
    def test_corrupt_history_is_not_replaced(self):
        from aura_body_memory import WorldMemory
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'body_world.db';path.write_bytes(b'not a database');before=path.read_bytes()
            virtual=body.Body(Clock());virtual.recorder=WorldMemory(path)
            virtual._remember('fault',{'reason':'fixture'})
            self.assertIn('unavailable',virtual.memory_status);self.assertEqual(path.read_bytes(),before)
    def test_memory_rejects_unsupported_events(self):
        from aura_body_memory import WorldMemory
        with tempfile.TemporaryDirectory() as folder:
            memory=WorldMemory(Path(folder)/'body_world.db')
            with self.assertRaises(ValueError):memory('run_shell',{'command':'anything'})
            with self.assertRaises(ValueError):memory('fault',{'value':float('nan')})
    def test_retention_cap(self):
        from aura_body_memory import WorldMemory
        with tempfile.TemporaryDirectory() as folder:
            memory=WorldMemory(Path(folder)/'body_world.db');memory('fault',{'reason':'fixture'})
            with contextlib.closing(memory.connect()) as db, db:
                db.executemany('INSERT INTO body_events(recorded,kind,payload) VALUES(?,?,?)',[('fixture','fault','{}')]*305)
            memory('fault',{'reason':'last'})
            with contextlib.closing(memory.connect()) as db:self.assertEqual(db.execute('SELECT count(*) FROM body_events').fetchone()[0],300)
            self.assertEqual(memory.recent()[0]['data']['reason'],'last')


if __name__=='__main__':unittest.main()
