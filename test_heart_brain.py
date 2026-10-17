"""Offline tests. All persistent state and repair targets are temporary fixtures."""
import asyncio
import contextlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
import aura_emotions as emotions
import aura_selfcare as care
from aura_autonomy import managed_route_stream


class Fixture(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.patches = [patch.object(emotions,'ROOT',self.root),
                        patch.object(emotions,'CONTROL',self.root/'brain_data'/'emotion_control.json'),
                        patch.object(care,'ROOT',self.root),patch.object(care,'_ACTIVE',False),patch.object(care,'_LAST_CHECK',0.)]
        for p in self.patches: p.start()
        for name in care.FILES: (self.root/name).write_text('x = 1\n')

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.folder.cleanup()

    def write(self,name,raw):
        path = self.root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(raw)
        return path


class EmotionTests(Fixture):
    def test_supportive_for_expressed_distress(self):
        for text in ['I am sad', "I'm very stressed", 'main bahut pareshan', 'Please be supportive']:
            self.assertEqual(emotions.select_style(text)['tone'],'supportive')

    def test_cheerful_for_explicit_good_news(self):
        self.assertEqual(emotions.select_style('I passed my exam')['tone'],'cheerful')

    def test_focused_for_debugging(self):
        self.assertEqual(emotions.select_style('Debug this error')['tone'],'focused')

    def test_no_hidden_emotion_claim(self):
        state = emotions.select_style('hello')
        self.assertEqual(state,{'tone':'calm','reason':'default response style'})

    def test_basic_negation_not_marked_distress(self):
        self.assertEqual(emotions.select_style('I am not sad')['tone'],'calm')

    def test_manual_and_off_persist(self):
        emotions.configure('cheerful')
        self.assertEqual(emotions.select_style('Explain a tree')['tone'],'cheerful')
        emotions.configure('off')
        self.assertIsNone(emotions.select_style('I am sad')['tone'])
        self.assertEqual(json.loads(emotions.CONTROL.read_text())['mode'],'off')

    def test_supportive_overrides_cheerful_but_not_off(self):
        emotions.configure('cheerful')
        self.assertEqual(emotions.select_style('I feel sad')['tone'],'supportive')

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError): emotions.configure('execute shell')

    def test_context_override_resets(self):
        token = emotions.CURRENT.set({'tone':'focused'})
        try: self.assertEqual(emotions.style_override('calm'),'focused')
        finally: emotions.CURRENT.reset(token)
        self.assertEqual(emotions.style_override('calm'),'calm')

    def test_installed_heart_prompt_uses_current_style(self):
        import aura_heart as heart
        token = emotions.CURRENT.set({'tone':'supportive'})
        try:
            text = heart.heart_prompt()
            self.assertIn('Acknowledge feelings',text)
            self.assertIn('no real feelings',text)
        finally: emotions.CURRENT.reset(token)

    def test_corrupt_control_has_safe_default(self):
        self.write('brain_data/emotion_control.json','invalid json')
        self.assertEqual(emotions.control()['mode'],'auto')


class SelfCareTests(Fixture):
    def test_clean_project(self):
        self.assertEqual(care.inspect(),[])

    def test_known_launcher_repair_with_exact_backup(self):
        original = "def launch():\n    server.app.add_event_handler('startup', ready.set)\n"
        path = self.write('run_aura.py',original)
        result = care.repair_known()
        self.assertEqual(result['repaired'],['run_aura.py'])
        self.assertIn('ready.set()',path.read_text())
        backups = list((self.root/'selfcare_backups').rglob('run_aura.py'))
        self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].read_text(),original)
        self.assertEqual(care.repair_known()['repaired'],[])

    def test_malformed_settings_repaired_and_backed_up(self):
        self.write('brain_data/heart.json','broken')
        self.write('brain_data/emotion_control.json','[]')
        result = care.repair_known()
        self.assertEqual(len(result['repaired']),2)
        self.assertEqual(json.loads((self.root/'brain_data'/'heart.json').read_text()),care.DEFAULTS['heart.json'])
        self.assertTrue(list((self.root/'selfcare_backups').rglob('heart.json')))

    def test_unknown_syntax_not_modified(self):
        path = self.write('aura_brain.py','def broken(:\n')
        before = path.read_bytes()
        result = care.repair_known()
        self.assertEqual(path.read_bytes(),before)
        self.assertTrue(any(i['issue']=='python_syntax' and not i['repairable'] for i in result['unresolved']))

    def test_database_is_only_checked(self):
        path = self.root/'memory.db'
        with contextlib.closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE fixture (value TEXT)')
            db.execute("INSERT INTO fixture VALUES ('preserve me')")
        before = path.read_bytes()
        care.repair_known()
        self.assertEqual(path.read_bytes(),before)

    def test_invalid_database_not_repaired(self):
        path = self.write('memory.db','not a database')
        before = path.read_bytes()
        result = care.repair_known()
        self.assertEqual(path.read_bytes(),before)
        self.assertTrue(any(i['file']=='memory.db' and not i['repairable'] for i in result['unresolved']))

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError): care.safe_path('../outside.txt')

    def test_symlink_target_not_repaired(self):
        (self.root/'run_aura.py').unlink()
        target = self.root/'untouched.py'
        target.write_text("server.app.add_event_handler('startup', ready.set)")
        try: (self.root/'run_aura.py').symlink_to(target)
        except OSError: self.skipTest('Symlink creation unavailable on this Windows account')
        before = target.read_bytes()
        self.assertEqual(care.repair_known()['repaired'],[])
        self.assertEqual(target.read_bytes(),before)

    def test_valid_preferences_not_reset(self):
        path = self.write('brain_data/heart.json',json.dumps({'tone':'focused','verbosity':'detailed'}))
        before = path.read_bytes()
        care.repair_known()
        self.assertEqual(path.read_bytes(),before)

    def test_auto_off_stops_repairs(self):
        care.activate()
        care.set_enabled(False)
        self.write('brain_data/heart.json','bad json')
        self.assertIsNone(care.tick(force=True))
        self.assertEqual((self.root/'brain_data'/'heart.json').read_text(),'bad json')

    def test_active_tick_repairs_known_error(self):
        care.activate()
        self.write('brain_data/heart.json','bad json')
        result = care.tick(force=True)
        self.assertEqual(len(result['repaired']),1)
        self.assertIsNone(care.tick())

    def test_backup_failure_prevents_repair(self):
        path = self.write('brain_data/heart.json','bad json')
        actual = care.write_bytes
        def fail_backup(p,raw):
            if 'selfcare_backups' in p.parts: raise OSError('simulated backup failure')
            return actual(p,raw)
        with patch.object(care,'write_bytes',side_effect=fail_backup):
            self.assertEqual(care.repair_known()['repaired'],[])
        self.assertEqual(path.read_text(),'bad json')

    def test_failed_candidate_verification_restores_original(self):
        path = self.write('brain_data/heart.json','original invalid json')
        actual = care.write_bytes
        failed = []
        def damage_candidate(p,raw):
            if p == path and not failed:
                failed.append(True)
                return actual(p,b'unexpected disk contents')
            return actual(p,raw)
        with patch.object(care,'write_bytes',side_effect=damage_candidate):
            self.assertEqual(care.repair_known()['repaired'],[])
        self.assertEqual(path.read_text(),'original invalid json')

    def test_audit_does_not_store_exception_contents(self):
        care.record('request_failed')
        events = json.loads((self.root/'brain_data'/'selfcare_events.json').read_text())
        self.assertEqual(set(events[0]),{'time','event'})


class AutonomyTests(Fixture):
    def test_managed_startup_checks_before_launch(self):
        import run_aura_managed as launcher
        self.write('brain_data/heart.json','invalid')
        calls = []
        probe = MagicMock()
        probe.__enter__.return_value.connect_ex.return_value = 1
        def launch():
            self.assertTrue(care.valid_settings('heart.json',json.loads((self.root/'brain_data'/'heart.json').read_text())))
            calls.append('launched')
        with patch.object(launcher.socket,'socket',return_value=probe), patch.dict('sys.modules',{'run_aura':SimpleNamespace(main=launch)}), patch('builtins.print'):
            launcher.main()
        self.assertEqual(calls,['launched'])

    def test_busy_port_refuses_duplicate_start(self):
        import run_aura_managed as launcher
        probe = MagicMock()
        probe.__enter__.return_value.connect_ex.return_value = 0
        with patch.object(launcher.socket,'socket',return_value=probe), self.assertRaises(SystemExit):
            launcher.main()
        self.assertFalse((self.root/'brain_data').exists())

    def collect(self,text):
        async def original(*args): raise AssertionError('A local command must not call AI'); yield
        async def run():
            return [e async for e in managed_route_stream(original,None,'fixture',text,[],'')]
        return asyncio.run(run())

    def test_local_emotion_command(self):
        events = self.collect('/emotion focused')
        self.assertEqual(events[0]['name'],'selfcare')
        self.assertEqual(emotions.control(),{'mode':'manual','tone':'focused'})

    def test_local_selfcheck_and_repair(self):
        self.assertIn('0 unresolved',self.collect('/selfcheck')[1]['text'])
        self.write('brain_data/heart.json','invalid')
        self.assertIn('1 known repairs',self.collect('/repair')[1]['text'])

    def test_local_autocare_toggle(self):
        self.collect('/autocare off')
        self.assertFalse(care.enabled())

    def test_no_maintenance_from_embedded_text(self):
        seen = []
        async def original(*args):
            seen.append(args[2])
            yield {'type':'route','name':'general'}
            yield {'type':'token','text':'normal answer'}
        async def run():
            return [e async for e in managed_route_stream(original,None,'fixture','Explain the string /repair',[],'')]
        self.assertEqual(asyncio.run(run())[0]['name'],'general')
        self.assertEqual(seen,['Explain the string /repair'])

    def test_request_context_reaches_worker_and_resets(self):
        seen = []
        async def original(*args):
            seen.append(await asyncio.to_thread(emotions.style_override,'calm'))
            yield {'type':'route','name':'general'}
        async def run():
            events = [e async for e in managed_route_stream(original,None,'fixture','I am sad',[],'')]
            self.assertEqual(events[0]['emotion'],'supportive')
            self.assertIsNone(emotions.CURRENT.get())
        asyncio.run(run())
        self.assertEqual(seen,['supportive'])

    def test_error_resets_style_and_logs_category(self):
        async def original(*args): raise RuntimeError('API-SECRET'); yield
        async def run():
            with self.assertRaises(RuntimeError):
                async for _ in managed_route_stream(original,None,'fixture','Debug this',[],''): pass
            self.assertIsNone(emotions.CURRENT.get())
        asyncio.run(run())
        self.assertNotIn('API-SECRET',(self.root/'brain_data'/'selfcare_events.json').read_text())

    def test_stop_closes_original_stream(self):
        closed = []
        async def original(*args):
            try:
                yield {'type':'route','name':'general'}
                await asyncio.Future()
            finally: closed.append(True)
        async def run():
            async with contextlib.aclosing(managed_route_stream(original,None,'fixture','hello',[],'')) as stream:
                await anext(stream)
            self.assertIsNone(emotions.CURRENT.get())
        asyncio.run(run())
        self.assertEqual(closed,[True])


if __name__=='__main__': unittest.main()
