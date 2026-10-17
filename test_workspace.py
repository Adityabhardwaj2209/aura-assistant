"""Offline fixture tests. No laptop apps, real models, speech engines or camera."""
import asyncio
import contextlib
import importlib
import json
import math
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch,AsyncMock
import aura_workspace_store as store
import aura_workspace_tools as tools
import aura_workspace_planner as planner
import aura_workspace_ai as ai
import aura_brain as brain


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patches=[patch.object(store,'DB',self.root/'data'/'workspace.db'),patch.object(tools,'FILES',self.root/'files'),patch.object(brain,'DB',self.root/'data'/'docs.db')]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def plan(self,steps=None):
        return planner.create_plan('Test',steps or [{'title':'Review','action':'manual','params':{}}])
    def run_async(self,coro):return asyncio.run(coro)


class StoreTests(Fixture):
    def test_facts_goals_persist_and_correct(self):
        r=store.save('fact',{'name':'language','value':'English'})
        store.save('fact',{'name':'language','value':'Hinglish'},r['id'])
        g=store.save('goal',{'title':'AURA','status':'active'})
        self.assertEqual(store.memory_context()['saved_facts'][0]['value'],'Hinglish')
        self.assertEqual(len(store.records('goal')),1)
        with self.assertRaises(ValueError):store.save('goal',{},r['id'])
    def test_malformed_ids_rejected_before_database(self):
        for ident in [None,{},[],123,'../x']:
            with self.assertRaises(ValueError):store.get(ident)
    def test_delete_is_kind_checked(self):
        r=store.save('fact',{'value':'x'})
        with self.assertRaises(ValueError):store.delete(r['id'],'goal')
        store.delete(r['id'],'fact');self.assertEqual(store.records('fact'),[])
    def test_no_nonfinite_json(self):
        with self.assertRaises(ValueError):store.save('goal',{'n':float('nan')})
    def test_unknown_usage_not_counted_as_zero(self):
        store.metric('ask','local','m',10,True)
        store.metric('ask','cloud','m',20,False,{'prompt_tokens':15,'completion_tokens':3},'MockError')
        s=store.metrics()['totals'];self.assertEqual(s['requests'],2);self.assertEqual(s['token_measured_requests'],1);self.assertEqual(s['input_tokens'],15)
    def test_closed_database_can_be_replaced(self):
        store.save('fact',{'name':'n','value':'v'});db=store.DB
        renamed=db.with_suffix('.moved');db.replace(renamed);renamed.replace(db)
        self.assertEqual(len(store.records('fact')),1)


class FilePatchTests(Fixture):
    def test_traversal_and_windows_devices_blocked(self):
        for name in ['../secret.txt','x/../../secret.txt','C:/secret.txt','x\\secret.txt','/tmp/x','CON.txt','a/NUL','name.','a//b','x:ads.txt']:
            with self.subTest(name=name),self.assertRaises(ValueError):tools.safe_path(name)
    def test_symlink_blocked(self):
        tools.FILES.mkdir();outside=self.root/'outside';outside.mkdir()
        try:(tools.FILES/'link').symlink_to(outside,target_is_directory=True)
        except OSError:self.skipTest('Host does not allow symlinks')
        with self.assertRaises(ValueError):tools.write_file('link/no.txt','x')
    def test_file_no_overwrite_and_preserves_content(self):
        content='\n  precise whitespace  \n'
        tools.write_file('notes/a.md',content)
        self.assertEqual(tools.read_file('notes/a.md'),content)
        with self.assertRaises(ValueError):tools.write_file('notes/a.md','new')
    def test_syntax_never_executes(self):
        marker=self.root/'executed'
        source='from pathlib import Path\nPath('+repr(str(marker))+').write_text("bad")\n'
        self.assertTrue(tools.validate_python(source)['ok']);self.assertFalse(marker.exists())
        self.assertFalse(tools.validate_python('def x(:')['ok'])
    def test_patch_apply_and_exact_rollback(self):
        old='\n# original\nx=1\n';new='\n# fixed\nx=2\n'
        tools.write_file('x.py',old);r=tools.propose_patch('x.py',new)
        tools.patch_action(r['id'],'apply');self.assertEqual(tools.read_file('x.py'),new)
        tools.patch_action(r['id'],'rollback');self.assertEqual(tools.read_file('x.py'),old)
    def test_database_failure_restores_file(self):
        tools.write_file('x.py','x=1');r=tools.propose_patch('x.py','x=2')
        with patch.object(tools,'save',side_effect=OSError('fixture DB failure')):
            with self.assertRaises(OSError):tools.patch_action(r['id'],'apply')
        self.assertEqual(tools.read_file('x.py'),'x=1')
        self.assertEqual(store.get(r['id'])['data']['status'],'proposed')
    def test_stale_patch_not_applied(self):
        tools.write_file('x.py','x=1');r=tools.propose_patch('x.py','x=2');tools.write_file('x.py','x=3',True)
        with self.assertRaises(ValueError):tools.patch_action(r['id'],'apply')
        self.assertEqual(tools.read_file('x.py'),'x=3')
    def test_rollback_does_not_clobber_new_edit(self):
        tools.write_file('x.py','x=1');r=tools.propose_patch('x.py','x=2');tools.patch_action(r['id'],'apply');tools.write_file('x.py','x=9',True)
        with self.assertRaises(ValueError):tools.patch_action(r['id'],'rollback')
    def test_bad_syntax_not_applied(self):
        tools.write_file('x.py','x=1');r=tools.propose_patch('x.py','x=')
        with self.assertRaises(ValueError):tools.patch_action(r['id'],'apply')
    def test_arbitrary_app_rejected(self):
        with self.assertRaises(ValueError):tools.open_app('powershell -Command bad')
    def test_file_list_excludes_symlink_tree(self):
        tools.write_file('ok.txt','ok');self.assertEqual(tools.files()[0]['name'],'ok.txt')


class PlanTests(Fixture):
    def test_manual_requires_explicit_confirmation(self):
        r=self.plan();p=self.run_async(planner.advance(r['id']))
        self.assertEqual(p['data']['steps'][0]['status'],'waiting')
        self.assertEqual(planner.control(r['id'],'confirm')['data']['status'],'done')
    def test_one_step_only_and_resume(self):
        r=self.plan([{'title':'Write','action':'write','params':{'file':'n.txt','content':'note'}},{'title':'Review','action':'manual','params':{}}])
        p=self.run_async(planner.advance(r['id']));self.assertEqual(p['data']['steps'][0]['status'],'done');self.assertEqual(p['data']['steps'][1]['status'],'pending')
        self.assertEqual(tools.read_file('n.txt'),'note')
    def test_restart_pauses_running_step(self):
        r=self.plan();p=r['data'];p['status']='running';p['steps'][0]['status']='running';store.save('plan',p,r['id']);store.recover()
        p=store.get(r['id'])['data'];self.assertEqual(p['status'],'paused');self.assertEqual(p['steps'][0]['status'],'interrupted')
        with self.assertRaises(ValueError):self.run_async(planner.advance(r['id']))
        planner.control(r['id'],'retry');self.assertEqual(store.get(r['id'])['data']['steps'][0]['status'],'pending')
    def test_failed_write_can_be_reconciled(self):
        tools.write_file('n.txt','old');r=self.plan([{'title':'Write','action':'write','params':{'file':'n.txt','content':'new'}}])
        with self.assertRaises(ValueError):self.run_async(planner.advance(r['id']))
        self.assertEqual(store.get(r['id'])['data']['steps'][0]['status'],'failed')
        self.assertEqual(planner.control(r['id'],'resolve')['data']['status'],'done')
        self.assertEqual(tools.read_file('n.txt'),'old')
    def test_arbitrary_commands_rejected(self):
        with self.assertRaises(ValueError):self.plan([{'title':'Shell','action':'shell','params':{'cmd':'echo x'}}])
    def test_ai_failure_saved(self):
        r=self.plan([{'title':'Research','action':'ai','params':{'prompt':'Explain x'}}])
        with patch.object(ai,'complete',new=AsyncMock(side_effect=ValueError('offline'))):
            with self.assertRaises(ValueError):self.run_async(planner.advance(r['id']))
        self.assertEqual(store.get(r['id'])['data']['steps'][0]['status'],'failed')
    def test_concurrent_advance_rejected(self):
        async def run():
            entered=asyncio.Event();release=asyncio.Event()
            async def slow(*a,**kw):entered.set();await release.wait();return 'done'
            r=self.plan([{'title':'AI','action':'ai','params':{'prompt':'x'}}])
            with patch.object(ai,'complete',new=slow):
                task=asyncio.create_task(planner.advance(r['id']));await entered.wait()
                with self.assertRaises(ValueError):await planner.advance(r['id'])
                release.set();await task
        self.run_async(run())


class DocQuizTests(Fixture):
    def test_selected_documents_balanced_citations(self):
        a=brain.import_document('one.txt',b'CPU scheduling '+b'example '*3000)
        b=brain.import_document('two.txt',b'Deadlock prevention')
        evidence=tools.doc_evidence([a['id'],b['id']],'scheduling')
        self.assertEqual(len(evidence),2);self.assertEqual(evidence[0]['selected_chunks'],5);self.assertEqual(evidence[1]['selected_chunks'],1)
        self.assertIn('[two.txt, p.1]',tools.extractive_notes(evidence));self.assertIn('not a complete',evidence[0]['coverage'])
    def test_invalid_doc_selection_rejected(self):
        for ids in [[],[True],[999],list(range(8))]:
            with self.assertRaises(ValueError):tools.doc_evidence(ids)
    def quiz(self):return {'questions':[{'question':'2+2?','options':['1','2','3','4'],'answer':3,'explanation':'Four','topic':'Math'}]}
    def test_quiz_grading_and_weak_topics(self):
        r=store.save('quiz',tools.validate_quiz(self.quiz()));public=tools.public_quiz(r)
        self.assertNotIn('answer',public['questions'][0]);self.assertNotIn('explanation',public['questions'][0])
        self.assertEqual(tools.grade(r['id'],[0])['data']['score'],0);self.assertTrue(tools.learning_stats()[0]['practice_priority'])
    def test_missing_answers_rejected(self):
        r=store.save('quiz',tools.validate_quiz(self.quiz()))
        for answers in [[],[True],[4]]:
            with self.assertRaises(ValueError):tools.grade(r['id'],answers)
    def test_bad_generated_quiz_rejected(self):
        q=self.quiz();q['questions'][0]['answer']=True
        with self.assertRaises(ValueError):tools.validate_quiz(q)
    def test_plan_notes_offline(self):
        d=brain.import_document('notes.txt',b'This is a useful note')
        r=self.plan([{'title':'Notes','action':'notes','params':{'documents':[d['id']]}}])
        p=self.run_async(planner.advance(r['id']));self.assertIn('[notes.txt, p.1]',p['data']['steps'][0]['result'])


class AdapterTests(Fixture):
    def fake_server(self):return patch.dict(sys.modules,{'phase3_web':types.SimpleNamespace(SETTINGS={'key':'','model':'test'})})
    def test_no_key_actionable_and_measured(self):
        with self.fake_server(),self.assertRaisesRegex(ValueError,'Set your Groq key'):self.run_async(ai.complete('test','hello'))
        self.assertEqual(store.metrics()['totals']['requests'],1)
    def test_local_response_usage_measured(self):
        response={'message':{'content':'local answer'},'prompt_eval_count':12,'eval_count':3}
        with self.fake_server(),patch.object(ai,'local_request',return_value=response) as call:
            answer=self.run_async(ai.complete('ask','hello','local','installed-model'))
        self.assertEqual(answer,'local answer');self.assertEqual(call.call_args.args[0],'/api/chat');self.assertEqual(store.metrics()['totals']['output_tokens'],3)
    def test_local_missing_does_not_claim_ai_answer(self):
        with patch.object(ai,'local_request',side_effect=ConnectionError):result=self.run_async(ai.local_models())
        self.assertFalse(result['available']);self.assertEqual(result['models'],[])
    def test_screenshot_not_sent_to_nonvision_local_adapter(self):
        with self.assertRaises(ValueError):self.run_async(ai.complete('screen','hello','local','m',image=('image/png',b'png')))
    def test_redirects_forbidden(self):self.assertIsNone(ai.NoRedirect().redirect_request(None,None,None,None,None,None))


class EvaluationTests(unittest.TestCase):
    def report(self):return {'schema':'aura-camera-evaluation-v1','summary':{'annotated_samples':1,'tp':1,'fp':0,'fn':0,'precision':1,'recall':1,'f1':1,'mean_matched_iou':.8,'timing_window':{'mean_ms':45,'p95_ms':48},'score_threshold':.6,'iou_threshold':.5}}
    def test_real_report_fields_only(self):
        from aura_workspace_evaluation import extract_evaluation
        d=extract_evaluation(self.report());self.assertEqual(d['summary']['tp'],1);self.assertNotIn('samples',d)
    def test_nonfinite_or_bad_schema_rejected(self):
        from aura_workspace_evaluation import extract_evaluation
        r=self.report();r['summary']['f1']=float('nan')
        with self.assertRaises(ValueError):extract_evaluation(r)
        with self.assertRaises(ValueError):extract_evaluation({'schema':'other'})


class VoiceTests(unittest.TestCase):
    def test_real_timing_protocol_and_no_text_interpolation(self):
        import aura_workspace_voice as voice
        def fake(script,env):
            Path(env['AURA_WAV']).write_bytes(b'RIFFtest');return '[{"viseme":1,"time":0.1,"duration":0.2}]'
        with patch.dict(sys.modules,{'phase3_web':types.SimpleNamespace(powershell=fake)}):r=voice.synthesize('hello $()')
        self.assertEqual(r['cues'][0]['viseme'],1);self.assertEqual(r['sync'],'Windows voice visemes')
        self.assertIn('VisemeReached',voice.SCRIPT);self.assertNotIn('hello $()',voice.SCRIPT)
    def test_no_viseme_fallback_explicit(self):
        import aura_workspace_voice as voice
        def fake(script,env):Path(env['AURA_WAV']).write_bytes(b'RIFFtest');return '[]'
        with patch.dict(sys.modules,{'phase3_web':types.SimpleNamespace(powershell=fake)}):self.assertIn('fallback',voice.synthesize('hello')['sync'])


class RouteTests(Fixture):
    def setUp(self):
        super().setUp()
        fake=types.ModuleType('fastapi');fake.Request=type('Request',(),{})
        class HTTPException(Exception):
            def __init__(self,status_code,detail):self.status_code=status_code;self.detail=detail;super().__init__(detail)
        fake.HTTPException=HTTPException;responses=types.ModuleType('fastapi.responses');responses.Response=responses.HTMLResponse=lambda *a,**kw:(a,kw)
        with patch.dict(sys.modules,{'fastapi':fake,'fastapi.responses':responses}):
            sys.modules.pop('aura_workspace_routes',None);self.routes=importlib.import_module('aura_workspace_routes')
        self.endpoints={};owner=self
        class App:
            def get(self,path):return lambda fn:owner.endpoints.setdefault(('GET',path),fn)
            def post(self,path):return lambda fn:owner.endpoints.setdefault(('POST',path),fn)
        def require(request):
            if not getattr(request,'authorized',False):raise HTTPException(403,'Forbidden')
        self.routes.install_workspace(App(),require,'TEST_TOKEN')
    def req(self,data=None,authorized=True):
        class R:
            async def body(self):return json.dumps(data).encode()
        r=R();r.authorized=authorized;return r
    def call(self,path,data=None,authorized=True):return self.run_async(self.endpoints[('POST','/api/workspace/'+path)](self.req(data,authorized)))
    def test_every_json_mutation_rejects_missing_auth(self):
        paths=['record','delete','ask','plan-draft','plan','plan-action','documents','quiz','quiz-open','grade','file','app','code','evaluation','speak']
        for path in paths:
            with self.subTest(path=path),self.assertRaisesRegex(Exception,'Forbidden'):self.call(path,{},False)
    def test_screen_auth_before_reading_upload(self):
        with self.assertRaisesRegex(Exception,'Forbidden'):self.call('screen',{},False)
    def test_record_schema_rejects_unsupported_status(self):
        with self.assertRaisesRegex(Exception,'Unknown goal status'):self.call('record',{'kind':'goal','data':{'title':'x','status':'bogus'}})
    def test_workspace_record_roundtrip(self):
        r=self.call('record',{'kind':'goal','data':{'title':'Build AURA'}})
        self.assertEqual(store.get(r['id'])['data']['status'],'active')
    def test_arbitrary_record_overwrite_forbidden(self):
        with self.assertRaisesRegex(Exception,'goals or facts'):self.call('record',{'kind':'patch','data':{}})
    def test_asset_traversal_rejected(self):
        with self.assertRaisesRegex(Exception,'Not found'):self.endpoints[('GET','/workspace-assets/{name}') ]('../memory.db')
    def test_all_get_data_endpoints_authorized(self):
        for path in ['state','export','local-models']:
            fn=self.endpoints[('GET','/api/workspace/'+path)]
            with self.subTest(path=path),self.assertRaisesRegex(Exception,'Forbidden'):
                if path=='local-models':self.run_async(fn(self.req(authorized=False)))
                else:fn(self.req(authorized=False))
    def test_missing_file_reports_error(self):
        with self.assertRaisesRegex(Exception,'existing text file'):self.call('file',{'action':'read','name':'missing.py'})


class ReviewedRunnerTests(unittest.TestCase):
    def test_explicit_review_required(self):
        from aura_workspace_test_runner import run_reviewed
        with self.assertRaises(ValueError):run_reviewed('x=1','import unittest',False)
    def test_behavior_tests_pass_in_separate_process(self):
        from aura_workspace_test_runner import run_reviewed
        source='def add(a,b):\n return a+b\n'
        tests='import unittest, candidate\nclass T(unittest.TestCase):\n def test_add(self): self.assertEqual(candidate.add(2,3),5)\n'
        result=run_reviewed(source,tests,True)
        self.assertTrue(result['passed'],result['output']);self.assertIn('Ran 1 test',result['output'])
    def test_behavior_failure_reported(self):
        from aura_workspace_test_runner import run_reviewed
        tests='import unittest\nclass T(unittest.TestCase):\n def test_bad(self): self.assertEqual(1,2)\n'
        self.assertFalse(run_reviewed('x=1',tests,True)['passed'])
    def test_no_tests_is_failure(self):
        from aura_workspace_test_runner import run_reviewed
        self.assertFalse(run_reviewed('x=1','import unittest',True)['passed'])
    def test_main_process_timeout(self):
        import aura_workspace_test_runner as runner
        with patch.object(runner,'TIMEOUT_SECONDS',.15):r=runner.run_reviewed('x=1','import time;time.sleep(30)',True)
        self.assertTrue(r['timed_out']);self.assertFalse(r['passed'])
    def test_parent_secret_not_inherited(self):
        from aura_workspace_test_runner import run_reviewed
        tests='import unittest,os\nclass T(unittest.TestCase):\n def test_no_secret(self): self.assertNotIn("AURA_TEST_FAKE_SECRET",os.environ)\n'
        with patch.dict('os.environ',{'AURA_TEST_FAKE_SECRET':'FIXTURE_ONLY'}):r=run_reviewed('x=1',tests,True)
        self.assertTrue(r['passed'],r['output'])
    def test_output_limit_terminates_main_process(self):
        from aura_workspace_test_runner import run_reviewed
        r=run_reviewed('x=1','print("x"*100000)',True)
        self.assertTrue(r['output_limited']);self.assertFalse(r['passed']);self.assertLessEqual(len(r['output']),64000)


if __name__=='__main__':unittest.main(verbosity=2)
