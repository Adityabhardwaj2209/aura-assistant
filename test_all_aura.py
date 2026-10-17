"""Isolated AURA tests. Never uses a real API key or changes live databases."""
import argparse
import ast
import asyncio
import contextlib
import importlib.util
import io
import json
import os
import shutil
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument('--model',action='store_true',help='Also load/download the real embedding model for a smoke test')
parser.add_argument('--server',action='store_true',help='Check the already running local server without a key')
parser.add_argument('--isolated',action='store_true',help=argparse.SUPPRESS)
args=parser.parse_args()

if not args.isolated:
    required=['aura_brain.py','phase3_web.py','aura_web.py']
    missing=[name for name in required if not (ROOT/name).exists()]
    if missing:raise SystemExit('Run beside your AURA code. Missing: '+', '.join(missing))
    with tempfile.TemporaryDirectory(prefix='aura_tests_') as folder:
        target=Path(folder)
        for name in ['test_all_aura.py','aura_perception.py','aura_body.py','aura_organs.py','aura_emotions.py','aura_selfcare.py','aura_autonomy.py','aura_reliability.py','aura_followup.py','aura_router.py','aura_brain.py','aura_web.py','aura_heart.py','aura_semantic.py','phase3_web.py','brain_routes.py','run_aura.py','phase2_fixed.html','phase2.html']:
            if (ROOT/name).exists():shutil.copy2(ROOT/name,target/name)
        command=[sys.executable,str(target/'test_all_aura.py'),'--isolated']
        if args.model:command.append('--model')
        if args.server:command.append('--server')
        env=os.environ.copy()
        env['AURA_TEST_CACHE']=str(ROOT/'brain_data'/'embedding_models')
        result=subprocess.run(command,cwd=target,env=env,text=True,capture_output=True)
        report=result.stdout+result.stderr
        print(report)
        path=ROOT/'aura_test_report.txt'
        path.write_text(report,encoding='utf-8')
        print('Report saved: '+str(path))
        raise SystemExit(result.returncode)

import aura_brain as brain
try:
    import aura_heart as heart
except ImportError:
    heart=None
try:
    import numpy as np
    import aura_semantic as semantic
except ImportError:
    semantic=None


class FakeEmbedding:
    def embed(self,texts,**kwargs):
        for text in texts:
            text=text.casefold()
            if any(x in text for x in ['automobile','petrol','cars','fuel']):yield np.array([1.,0.,0.])
            elif any(x in text for x in ['banana','fruit']):yield np.array([0.,1.,0.])
            else:yield np.array([0.,0.,1.])


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.old_db=brain.DB
        brain.DB=Path(self.folder.name)/'knowledge.db'
        if semantic is not None:
            self.old_model=semantic._MODEL
            semantic._MODEL=FakeEmbedding()
        if heart is not None:
            self.old_config=heart.CONFIG
            heart.CONFIG=Path(self.folder.name)/'heart.json'
        brain.initialize()

    def tearDown(self):
        brain.DB=self.old_db
        if semantic is not None:semantic._MODEL=self.old_model
        if heart is not None:heart.CONFIG=self.old_config
        self.folder.cleanup()

    def test_01_compile_all_modules(self):
        for path in ROOT.glob('*.py'):
            with self.subTest(file=path.name):compile(path.read_text(encoding='utf-8-sig'),str(path),'exec')

    def test_02_database_and_connection_close(self):
        self.assertEqual(brain.documents(),[])
        with brain.connect() as db:db.execute('SELECT 1')
        with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')

    def test_03_import_and_page_reference(self):
        brain.import_document('notes.txt',b'Nebula calibration threshold is 73 percent.')
        result=brain.search('Nebula calibration')
        self.assertEqual(result[0]['source'],'notes.txt')
        self.assertEqual(result[0]['page'],1)

    def test_04_duplicate_import(self):
        raw=b'Persistent project notes'
        brain.import_document('first.txt',raw)
        self.assertTrue(brain.import_document('second.md',raw)['duplicate'])
        self.assertEqual(len(brain.documents()),1)

    def test_05_persistent_knowledge(self):
        brain.import_document('saved.md',b'Zorblax engine has nine turbines.')
        brain.initialize()
        self.assertIn('nine turbines',brain.search('Zorblax')[0]['text'])

    def test_06_delete_document(self):
        doc=brain.import_document('delete.txt',b'Unique deletephrase example.')
        brain.delete_document(doc['id'])
        self.assertEqual(brain.search('deletephrase'),[])

    def test_07_invalid_documents(self):
        for name,raw in [('empty.txt',b''),('file.exe',b'hello'),('bad.txt',b'\xff'),('large.txt',b'a'*(brain.MAX_BYTES+1))]:
            with self.subTest(name=name),self.assertRaises(ValueError):brain.import_document(name,raw)

    def test_08_malformed_queries(self):
        for query in ['" OR * NOT NEAR(', '', '😀', 'DROP TABLE documents;']:
            brain.search(query)
        self.assertEqual(brain.documents(),[])

    def test_09_pdf_text_and_page_attribution(self):
        try:from pypdf import PdfWriter
        except ImportError:self.skipTest('pypdf unavailable')
        from pypdf.generic import DecodedStreamObject,DictionaryObject,NameObject
        writer=PdfWriter()
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        ref=writer._add_object(font)
        for text in ['Astronomy introduction','Zorblax engine has nine turbines']:
            page=writer.add_blank_page(width=600,height=800)
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):ref})})
            stream=DecodedStreamObject();stream.set_data(('BT /F1 12 Tf 40 700 Td ('+text+') Tj ET').encode())
            page[NameObject('/Contents')]=writer._add_object(stream)
        out=io.BytesIO();writer.write(out)
        brain.import_document('engine.pdf',out.getvalue())
        self.assertEqual(brain.search('Zorblax')[0]['page'],2)

    def test_10_prompt_uses_evidence(self):
        brain.import_document('evidence.txt',b'Nebula threshold is 73 percent.')
        prompt=brain.build_prompt('Nebula threshold','User prefers Java')
        self.assertIn('73 percent',prompt)
        self.assertIn('User prefers Java',prompt)
        self.assertIn('not instructions',prompt)

    def test_11_heart_settings_and_invalid_values(self):
        if heart is None:self.skipTest('Heart not installed')
        heart.configure('supportive','short')
        self.assertEqual(heart.settings()['tone'],'supportive')
        with self.assertRaises(ValueError):heart.configure('unsupported')
        heart.CONFIG.write_text('invalid json')
        self.assertEqual(heart.settings()['tone'],'calm')

    def test_12_heart_brain_integration(self):
        if heart is None:self.skipTest('Heart not installed')
        heart.configure('focused')
        self.assertIn('direct and practical',brain.build_prompt('hello'))

    def test_13_semantic_paraphrase_routing_mock(self):
        if semantic is None:self.skipTest('Semantic module/numpy unavailable')
        brain.import_document('motors.txt',b'Automobiles consume petrol.')
        brain.import_document('food.txt',b'Bananas are yellow fruit.')
        with contextlib.redirect_stdout(io.StringIO()):semantic.reindex()
        self.assertEqual(brain.keyword_search('Cars need fuel'),[])
        self.assertEqual(brain.search('Cars need fuel')[0]['source'],'motors.txt')
        self.assertEqual(semantic.status()['pending_passages'],0)

    def test_14_stale_vectors_excluded_mock(self):
        if semantic is None:self.skipTest('Semantic module/numpy unavailable')
        doc=brain.import_document('old.txt',b'Automobiles consume petrol.')
        with contextlib.redirect_stdout(io.StringIO()):semantic.reindex()
        brain.delete_document(doc['id'])
        brain.import_document('new.txt',b'Galaxies contain stars.')
        self.assertEqual(semantic.semantic_search('Cars need fuel'),[])
        self.assertEqual(semantic.status()['pending_passages'],1)

    def test_15_failed_index_atomicity_mock(self):
        if semantic is None:self.skipTest('Semantic module/numpy unavailable')
        brain.import_document('notes.txt',b'Automobiles consume petrol.')
        with contextlib.redirect_stdout(io.StringIO()):semantic.reindex()
        with semantic.database() as db:before=db.execute('SELECT * FROM semantic_vectors').fetchall()
        class Broken:
            def embed(self,*a,**kw):raise RuntimeError('injected failure')
        semantic._MODEL=Broken()
        with self.assertRaises(RuntimeError):semantic.reindex()
        with semantic.database() as db:self.assertEqual(before,db.execute('SELECT * FROM semantic_vectors').fetchall())

    def test_16_semantic_failure_fallback_mock(self):
        if semantic is None:self.skipTest('Semantic module/numpy unavailable')
        brain.import_document('notes.txt',b'Unique calibration settings.')
        with semantic.database() as db:db.execute('INSERT INTO semantic_state VALUES(?,?)',('enabled_model',semantic.MODEL))
        with patch.object(semantic,'semantic_search',side_effect=RuntimeError('failure')),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(brain.search('calibration')[0]['source'],'notes.txt')

    def test_17_web_arguments_and_privacy_mock(self):
        from aura_web import web_reply
        calls=[]
        async def create(**kw):
            calls.append(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Research result'))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        self.assertEqual(asyncio.run(web_reply(client,'openai/gpt-oss-20b','current robotics')),'Research result')
        request=calls[0]
        self.assertEqual(request['tools'],[{'type':'browser_search'}])
        self.assertEqual(request['tool_choice'],'required')
        self.assertFalse(request['stream'])
        self.assertEqual(request['messages'][1]['content'],'current robotics')
        self.assertEqual(len(request['messages']),2)

    def test_18_web_invalid_model_and_empty_answer_mock(self):
        from aura_web import web_reply
        async def create(**kw):return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=''))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with self.assertRaises(ValueError):asyncio.run(web_reply(client,'unsupported','hello'))
        with self.assertRaises(ValueError):asyncio.run(web_reply(client,'openai/gpt-oss-20b',''))
        with self.assertRaises(ValueError):asyncio.run(web_reply(client,'openai/gpt-oss-20b','hello'))

    def test_19_local_token_and_origin_guards(self):
        tree=ast.parse((ROOT/'phase3_web.py').read_text(encoding='utf-8-sig'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='require')
        class HTTPException(Exception):
            def __init__(self,status_code,detail):self.status_code=status_code
        scope={'TOKEN':'test-session','HTTPException':HTTPException}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'guard','exec'),scope)
        scope['require'](SimpleNamespace(headers={'X-Aura-Token':'test-session','origin':'http://127.0.0.1:8511'}))
        for headers in [{},{'X-Aura-Token':'test-session','origin':'https://untrusted.example'}]:
            with self.assertRaises(HTTPException):scope['require'](SimpleNamespace(headers=headers))

    def test_20_frontend_and_launcher_compatibility(self):
        path=ROOT/'phase2_fixed.html'
        if not path.exists():self.skipTest('Connection-fix frontend not installed')
        html=path.read_text(encoding='utf-8')
        self.assertIn("api('/api/config'",html)
        self.assertIn("await import('three')",html)
        self.assertIn('Session rejected (403)',html)
        launcher=(ROOT/'run_aura.py').read_text(encoding='utf-8')
        self.assertNotIn("server.app.add_event_handler(",launcher,'Apply the documented FastAPI launcher compatibility fix first')
        self.assertIn("host='127.0.0.1'",launcher)

    def test_21_real_embedding_model_optional(self):
        if not args.model:self.skipTest('Use --model for real model download/inference')
        if semantic is None:self.fail('Semantic module/numpy unavailable')
        from fastembed import TextEmbedding
        semantic._MODEL=TextEmbedding(model_name=semantic.MODEL,cache_dir=os.environ['AURA_TEST_CACHE'],threads=2)
        self.assertEqual(semantic.self_test()['result'],'PASS')

    def test_22_running_server_optional(self):
        if not args.server:self.skipTest('Use --server to check the already running AURA server')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:8511/api/health',timeout=5) as response:
            self.assertEqual(json.load(response)['version'],'aura-connection-fix-1')
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            opener.open('http://127.0.0.1:8511/api/history',timeout=5)
        self.assertEqual(rejected.exception.code,403)

    def test_23_streaming_chat_web_and_audio_mock(self):
        from aura_web import web_reply
        tree=ast.parse((ROOT/'phase3_web.py').read_text(encoding='utf-8-sig'))
        node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='turn')
        node.decorator_list=[]
        class Stream:
            def __aiter__(self):
                async def chunks():
                    yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='Test reply'))])
                return chunks()
            async def close(self):pass
        class Client:
            def __init__(self,**kw):
                self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
                self.audio=SimpleNamespace(transcriptions=SimpleNamespace(create=self.transcribe))
            async def __aenter__(self):return self
            async def __aexit__(self,*a):pass
            async def create(self,**kw):
                if kw.get('tools'):return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Test research reply'))])
                return Stream()
            async def transcribe(self,**kw):return SimpleNamespace(text='/chat Transcribed fixture')
        class Audio:
            async def read(self,size):return b'RIFFmock-wav'
        class Request:
            def __init__(self,form):self.data=form
            async def form(self):return self.data
            async def is_disconnected(self):return False
        async def run(form):
            saved=[]
            ns=dict(asyncio=asyncio,json=json,secrets=secrets,time=time,contextlib=contextlib,Request=Request,require=lambda r:None,
                    SETTINGS={'key':'fake-test-key','model':'openai/gpt-oss-20b'},BUSY=asyncio.Lock(),AsyncGroq=Client,
                    preferences=lambda:'',build_prompt=brain.build_prompt,messages=lambda n:[],save_pair=lambda u,r:saved.append((u,r)),
                    REPLIES={},StreamingResponse=lambda content,**kw:content,error_hint=lambda e:type(e).__name__,web_reply=web_reply,route_stream=__import__('aura_router').route_stream)
            exec(compile(ast.Module(body=[node],type_ignores=[]),'turn','exec'),ns)
            packets=[json.loads(item) async for item in await ns['turn'](Request(form))]
            self.assertEqual([p['type'] for p in packets if p['type']!='route'],['user','token','done'])
            self.assertEqual(len(saved),1)
            self.assertIn(packets[-1]['id'],ns['REPLIES'])
        for form in [{'text':'/chat Hello'}, {'text':'/web current robotics'}, {'audio':Audio()}]:
            with self.subTest(mode='audio' if 'audio' in form else form['text']):asyncio.run(run(form))


print('AURA AUTOMATED TESTS — ISOLATED TEMPORARY DATABASES')
print('No real Groq requests. No microphone/camera/voice synthesis/hardware tests.')
suite=unittest.defaultTestLoader.loadTestsFromTestCase(CoreTests)
result=unittest.TextTestRunner(verbosity=2).run(suite)
print(f'RESULT: run={result.testsRun}, passed={result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped)}, failed={len(result.failures)}, errors={len(result.errors)}, skipped={len(result.skipped)}')
raise SystemExit(0 if result.wasSuccessful() else 1)
