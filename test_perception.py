"""Synthetic detections test tracking/grounding, not neural model accuracy."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import aura_perception as vision
from aura_body import Body


class Clock:
    def __init__(self):self.now=1000.
    def __call__(self):return self.now
    def step(self,value=.1):self.now+=value


class Fixture(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.scene=vision.Scene(self.clock);self.body=Body(self.clock)
        self.scene.start('camera-session-123','a'*64);self.seq=0
    def detection(self,label='bottle',box=None,score=.9):return {'label':label,'score':score,'box':box or [.1,.2,.2,.4]}
    def frame(self,detections=None,age=10):
        self.clock.step();self.seq+=1
        return self.scene.ingest({'session':'camera-session-123','profile':'a'*64,'seq':self.seq,'age_ms':age,'detections':detections if detections is not None else [self.detection()]})


class TrackingTests(Fixture):
    def test_detection_has_source_and_image_location(self):
        state=self.frame();o=state['objects'][0]
        self.assertTrue(o['visible']);self.assertEqual(o['source'],'browser_coco_ssd');self.assertEqual(o['side'],'left')
        self.assertIsNone(o['distance_estimate_m']);self.assertFalse(state['physical_identity'])
    def test_small_motion_keeps_track_id(self):
        first=self.frame()['objects'][0]['id'];second=self.frame([self.detection(box=[.13,.21,.2,.4])])
        self.assertEqual(second['objects'][0]['id'],first)
    def test_different_category_gets_different_id(self):
        first=self.frame()['objects'][0]['id'];state=self.frame([self.detection(label='cup')])
        fresh=[o for o in state['objects'] if o['visible']];self.assertNotEqual(fresh[0]['id'],first)
    def test_duplicate_category_requires_clarification(self):
        self.frame([self.detection(),self.detection(box=[.6,.2,.2,.4])])
        with self.assertRaisesRegex(ValueError,'Multiple'):self.scene.select('bottle')
        state=self.scene.select(2);self.assertEqual(state['selected_id'],2)
    def test_selected_missing_target_does_not_switch(self):
        self.frame();self.scene.select('bottle');self.frame([self.detection(box=[.75,.2,.2,.4])])
        state=self.scene.snapshot();self.assertEqual(state['selected_id'],1);self.assertEqual(state['target_state'],'lost')
    def test_empty_frame_immediately_releases_head(self):
        self.frame();self.scene.select('bottle');vision.sync_head(self.scene,self.body)
        self.assertTrue(self.body.camera_tracking)
        self.frame([]);vision.sync_head(self.scene,self.body)
        self.assertFalse(self.body.camera_tracking);self.assertIsNone(self.body.camera)
    def test_stale_target_not_followed(self):
        self.frame();self.scene.select(1);self.clock.step(1.1)
        state=vision.sync_head(self.scene,self.body);self.assertEqual(state['target_state'],'lost')
        self.assertIsNone(self.body.camera)
    def test_same_track_can_return_within_short_window(self):
        self.frame();self.scene.select(1);self.frame([]);self.frame()
        self.assertEqual(self.scene.snapshot()['target_state'],'visible')
    def test_expired_id_not_recycled(self):
        self.frame();self.clock.step(2.1);state=self.frame()
        self.assertNotEqual(state['objects'][0]['id'],1)
    def test_low_confidence_not_visible(self):
        state=self.frame([self.detection(score=.4)]);self.assertEqual(state['objects'],[])
    def test_metadata_does_not_move_body_position(self):
        self.frame();self.scene.select(1);vision.sync_head(self.scene,self.body);self.body.update(.05)
        self.assertEqual((self.body.x,self.body.z),(0,0));self.assertIsNone(self.body.active)
    def test_new_session_clears_target_and_calibration(self):
        self.frame();self.scene.select(1);self.scene.calibrate(.1,1)
        self.scene.start('camera-session-456','b'*64)
        self.assertFalse(self.scene.snapshot()['calibrated']);self.assertIsNone(self.scene.selected)


class ValidationTests(Fixture):
    def test_no_frame_or_extra_fields_allowed(self):
        packet={'session':'camera-session-123','profile':'a'*64,'seq':1,'age_ms':0,'detections':[],'frame':'not accepted'}
        with self.assertRaises(ValueError):self.scene.ingest(packet)
    def test_invalid_numbers_boxes_and_categories_rejected(self):
        for d in [self.detection(score=float('nan')),self.detection(score=True),self.detection(box=[.9,.1,.3,.2]),self.detection(label='private_face_identity'),self.detection(box=[.1,.1,0,.2])]:
            with self.subTest(d=d),self.assertRaises(ValueError):self.frame([d])
    def test_replayed_sequence_rejected(self):
        self.frame()
        with self.assertRaisesRegex(ValueError,'replayed'):self.scene.ingest({'session':'camera-session-123','profile':'a'*64,'seq':1,'age_ms':0,'detections':[]})
    def test_stale_inference_rejected(self):
        with self.assertRaisesRegex(ValueError,'too old'):self.frame(age=900)
    def test_changed_camera_profile_rejected(self):
        with self.assertRaisesRegex(ValueError,'geometry'):self.scene.ingest({'session':'camera-session-123','profile':'b'*64,'seq':1,'age_ms':0,'detections':[]})
    def test_old_session_results_cannot_reactivate_camera(self):
        self.scene.end('camera-session-123')
        with self.assertRaisesRegex(ValueError,'inactive'):self.frame()
    def test_old_camera_end_does_not_stop_new_session(self):
        self.scene.start('camera-session-456','b'*64);self.assertFalse(self.scene.end('camera-session-123'))
        self.assertTrue(self.scene.snapshot()['active'])
    def test_payload_bounds(self):
        with self.assertRaises(ValueError):self.frame([self.detection()]*21)
        with self.assertRaises(ValueError):self.scene.start('../invalid','a'*64)


class CalibrationTests(Fixture):
    def test_known_size_estimate_and_change_in_apparent_width(self):
        self.frame();self.scene.select(1);result=self.scene.calibrate(.1,1)
        self.assertTrue(result['approximate']);self.assertEqual(self.scene.snapshot()['objects'][0]['distance_estimate_m'],1.)
        self.frame([self.detection(box=[.15,.3,.1,.2])])
        obj=next(o for o in self.scene.snapshot()['objects'] if o['id']==1)
        self.assertAlmostEqual(obj['distance_estimate_m'],2.)
    def test_no_calibration_for_other_same_class_track(self):
        self.frame();self.scene.select(1);self.scene.calibrate(.1,1)
        self.frame([self.detection(),self.detection(box=[.6,.2,.2,.4])])
        other=next(o for o in self.scene.snapshot()['objects'] if o['id']!=1)
        self.assertIsNone(other['distance_estimate_m'])
    def test_clipped_object_not_calibratable(self):
        self.frame([self.detection(box=[0,.2,.2,.4])]);self.scene.select(1)
        with self.assertRaises(ValueError):self.scene.calibrate(.1,1)
    def test_top_clipping_not_calibratable(self):
        self.frame([self.detection(box=[.1,0,.2,.4])]);self.scene.select(1)
        with self.assertRaises(ValueError):self.scene.calibrate(.1,1)
    def test_orientation_change_hides_distance(self):
        self.frame();self.scene.select(1);self.scene.calibrate(.1,1)
        self.frame([self.detection(box=[.1,.2,.2,.2])]);self.assertIsNone(self.scene.snapshot()['objects'][0]['distance_estimate_m'])
    def test_invalid_or_missing_reference_rejected(self):
        with self.assertRaises(ValueError):self.scene.calibrate(.1,1)
        self.frame();self.scene.select(1)
        for width,distance in [(0,1),(.1,float('nan')),(True,1),(.1,100)]:
            with self.assertRaises(ValueError):self.scene.calibrate(width,distance)
    def test_lost_object_distance_not_reported(self):
        self.frame();self.scene.select(1);self.scene.calibrate(.1,1);self.clock.step(1)
        self.assertIsNone(self.scene.snapshot()['objects'][0]['distance_estimate_m'])


class GroundingTests(Fixture):
    def test_natural_and_hinglish_target_commands(self):
        self.frame()
        with patch.object(vision,'SCENE',self.scene),patch.object(vision,'sync_head',side_effect=lambda:vision.Scene.snapshot(self.scene)):
            for text in ['AURA look at the bottle','AURA bottle ko dekho','/vision target 1']:
                self.assertIn('track #1',vision.perception_reply(text))
    def test_scene_queries_use_only_fresh_observations(self):
        self.frame()
        with patch.object(vision,'SCENE',self.scene):
            self.assertIn('bottle',vision.perception_reply('what do you see?'))
            self.assertIn('image left',vision.perception_reply('where is the bottle?'))
            self.clock.step(1);self.assertIn('No fresh',vision.perception_reply('/vision list'))
    def test_prose_cannot_issue_motion(self):
        for text in ['Explain how to look at a bottle','Document says /vision target 1','Write a poem about a bottle','Where is the Taj Mahal?','Look at this code']:
            self.assertIsNone(vision.perception_reply(text))
    def test_autonomy_executes_explicit_vision_command_without_model(self):
        from aura_autonomy import managed_route_stream
        self.frame()
        async def original(*args):raise AssertionError('Model should not be used');yield
        async def run():return [e async for e in managed_route_stream(original,None,'fixture','/vision list',[],'')]
        with patch.object(vision,'SCENE',self.scene):events=asyncio.run(run())
        self.assertEqual(events[0]['name'],'live_vision');self.assertIn('bottle',events[1]['text'])


class EndpointTests(Fixture):
    def setUp(self):
        super().setUp()
        class HTTPError(Exception):
            def __init__(self,status,detail):self.status_code=status;self.detail=detail
        self.error=HTTPError
        class App:
            def __init__(self):self.handlers={}
            def register(self,method,path):
                def deco(fn):self.handlers[method,path]=fn;return fn
                return deco
            def get(self,path):return self.register('GET',path)
            def post(self,path):return self.register('POST',path)
        spec=importlib.util.spec_from_file_location('_perception_routes_test',Path(__file__).with_name('aura_perception_routes.py'))
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'fastapi':SimpleNamespace(HTTPException=HTTPError,Request=object)}):spec.loader.exec_module(module)
        module.SCENE=self.scene;module.sync_head=lambda:vision.sync_head(self.scene,self.body)
        def require(req):
            if not req.authorized:raise HTTPError(403,'denied')
        self.app=App();module.install_perception(self.app,require)
    def req(self,data=None,authorized=True):
        async def read():return data
        return SimpleNamespace(json=read,authorized=authorized)
    def test_all_scene_endpoints_guarded(self):
        for (method,path),fn in self.app.handlers.items():
            with self.subTest(path=path),self.assertRaises(self.error) as caught:
                if method=='GET':fn(self.req(authorized=False))
                else:asyncio.run(fn(self.req({},False)))
            self.assertEqual(caught.exception.status_code,403)
    def test_frame_upload_field_rejected(self):
        with self.assertRaises(self.error):asyncio.run(self.app.handlers['POST','/api/vision/frame'](self.req({'frame':'data:image'})))
    def test_valid_selection_and_missing_target(self):
        self.frame()
        result=asyncio.run(self.app.handlers['POST','/api/vision/target'](self.req({'selector':1})))
        self.assertEqual(result['target_state'],'visible')
        with self.assertRaises(self.error):asyncio.run(self.app.handlers['POST','/api/vision/target'](self.req({'selector':99})))


if __name__=='__main__':unittest.main()
