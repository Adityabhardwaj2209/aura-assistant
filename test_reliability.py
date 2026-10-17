"""Offline mixed-flow, failure recovery and real SQLite retrieval fixtures."""
import asyncio
import contextlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import aura_reliability as reliability
import aura_router as router
import aura_followup as followup
from test_router import Client


class MixedClient(Client):
    async def create(self, **kwargs):
        if kwargs.get('response_format'):
            self.calls.append(kwargs)
            payload = json.loads(kwargs['messages'][-1]['content'])
            topic = 'ContextTrace advantages' if payload['route'] == 'documents' else 'robotics research benefits'
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'query': topic, 'needs_clarification': False})))])
        return await super().create(**kwargs)


class MixedFlowTests(unittest.TestCase):
    def test_arithmetic_functions_and_percent_skip_model(self):
        async def run():
            for question in ['18% of 2500', 'sqrt(81)', 'abs(-7)', '2*pi']:
                client = Client()
                events = [e async for e in router.route_stream(client, 'fixture', question, [], '')]
                self.assertEqual(events[0]['name'], 'calculator')
                self.assertEqual(client.calls, [])
        asyncio.run(run())

    def test_local_topic_blocks_older_web_topic(self):
        history = [{'role':'user','content':'/web latest robotics research'},
                   {'role':'user','content':'Uploaded private notes about ProjectB'}]
        self.assertEqual(followup.previous_questions(history, 'web'), [])

    def test_web_topic_blocks_older_document_topic(self):
        history = [{'role':'user','content':'/docs ContextTrace methodology'},
                   {'role':'user','content':'/web latest robotics research'}]
        self.assertEqual(followup.previous_questions(history, 'documents'), [])

    def test_documents_followup_web_calculator_in_one_conversation(self):
        history = []
        brain = SimpleNamespace(documents=lambda: [], build_prompt=lambda *a: 'ContextTrace evidence')
        web = SimpleNamespace(web_reply=AsyncMock(return_value='Verified web fixture'))
        async def run():
            client = MixedClient()
            queries = [('/docs ContextTrace methodology', 'documents'),
                       ('/docs iske advantages?', 'documents'),
                       ('/web latest robotics research', 'web'),
                       ('/web its benefits?', 'web'),
                       ('/calc 18% of 2500', 'calculator')]
            for question, expected in queries:
                events = [event async for event in router.route_stream(client, 'fixture', question, history, '')]
                self.assertEqual(events[0]['name'], expected)
                reply = ''.join(e['text'] for e in events if e['type'] == 'token')
                self.assertTrue(reply)
                history.extend([{'role': 'user', 'content': question}, {'role': 'assistant', 'content': reply}])
                if question == '/docs iske advantages?':
                    self.assertEqual(events[0]['query'], 'ContextTrace advantages')
            self.assertIn('450', reply)
            self.assertEqual(web.web_reply.await_args_list[-1].args[-1], 'robotics research benefits')
            self.assertEqual(len(history), 10)
        with patch.dict('sys.modules', {'aura_brain': brain, 'aura_web': web}):
            asyncio.run(run())

    def test_automatic_route_then_rewrite(self):
        async def run():
            client = MixedClient('documents')
            events = [event async for event in router.route_stream(client, 'fixture', 'Iske advantages?', [{'role':'user','content':'Uploaded ContextTrace notes'}], '')]
            self.assertEqual(events[0]['query'], 'ContextTrace advantages')
            self.assertTrue(client.calls[0].get('tools'))
        brain = SimpleNamespace(documents=lambda: [], build_prompt=lambda *a: 'evidence')
        with patch.dict('sys.modules', {'aura_brain': brain}):
            asyncio.run(run())


class RecoveryTests(unittest.TestCase):
    def test_idle_timeout_closes_generator(self):
        closed = []
        async def source():
            try:
                yield {'type': 'route', 'name': 'general'}
                await asyncio.Future()
            finally:
                closed.append(True)
        async def run():
            with self.assertRaisesRegex(ValueError, 'timed out'):
                async for _ in reliability.bounded_stream(source()): pass
        with patch.object(reliability, 'IDLE_SECONDS', .01):
            asyncio.run(run())
        self.assertEqual(closed, [True])

    def test_stop_closes_source(self):
        closed = []
        async def source():
            try:
                yield {'type': 'token', 'text': 'partial'}
                await asyncio.Future()
            finally: closed.append(True)
        async def run():
            async with contextlib.aclosing(reliability.bounded_stream(source())) as stream:
                await anext(stream)
        asyncio.run(run())
        self.assertEqual(closed, [True])

    def test_cancel_propagates(self):
        async def source():
            raise asyncio.CancelledError()
            yield
        async def run():
            with self.assertRaises(asyncio.CancelledError):
                await anext(reliability.bounded_stream(source()))
        asyncio.run(run())

    def test_partial_reply_is_not_retried(self):
        attempts = []
        async def source():
            attempts.append(1)
            yield {'type': 'token', 'text': 'partial'}
            raise ConnectionError('secret-token-should-not-appear')
        async def run():
            received = []
            with self.assertRaisesRegex(ValueError, 'internet connection'):
                async for event in reliability.bounded_stream(source()): received.append(event)
            self.assertEqual(len(received), 1)
        asyncio.run(run())
        self.assertEqual(len(attempts), 1)

    def test_provider_status_hints(self):
        for status, phrase in [(401, 'key'), (403, 'access'), (429, 'rate limit'), (503, 'temporarily')]:
            error = RuntimeError('SENSITIVE RAW PROVIDER RESPONSE')
            error.status_code = status
            message = reliability.recovery_message(error)
            self.assertIn(phrase, message)
            self.assertNotIn('SENSITIVE', message)

    def test_unknown_error_does_not_leak_details(self):
        self.assertNotIn('secret', reliability.recovery_message(RuntimeError('secret')))

    def test_validation_error_is_actionable(self):
        self.assertEqual(reliability.recovery_message(ValueError('Include topic')), 'Include topic')

    def test_first_event_timeout(self):
        async def source():
            await asyncio.Future()
            yield
        async def run():
            with self.assertRaisesRegex(ValueError, 'timed out'):
                await anext(reliability.bounded_stream(source()))
        with patch.object(reliability, 'FIRST_EVENT_SECONDS', .01):
            asyncio.run(run())

    def test_total_deadline_bounds_continually_active_stream(self):
        async def source():
            while True:
                await asyncio.sleep(.005)
                yield {'type': 'token', 'text': '.'}
        async def run():
            with self.assertRaisesRegex(ValueError, 'timed out'):
                async for _ in reliability.bounded_stream(source()): pass
        with patch.object(reliability, 'TURN_SECONDS', .025):
            asyncio.run(run())

    def test_web_has_separate_wait_budget(self):
        async def source():
            yield {'type': 'route', 'name': 'web'}
            await asyncio.sleep(.03)
            yield {'type': 'token', 'text': 'web answer'}
        async def run():
            return [event async for event in reliability.bounded_stream(source())]
        with patch.object(reliability, 'IDLE_SECONDS', .005), patch.object(reliability, 'WEB_REPLY_SECONDS', .2):
            self.assertEqual(len(asyncio.run(run())), 2)


class RetrievalFixtureTests(unittest.TestCase):
    def test_real_sqlite_top_result_for_three_topics(self):
        import aura_brain as brain
        fixtures = [('contexttrace.txt', 'ContextTrace methodology uses provenance graphs and advantages include traceability.'),
                    ('gardening.txt', 'Gardening tomatoes require sunlight and watering.'),
                    ('compiler.txt', 'Compiler parsing builds syntax trees with grammar productions.')]
        with tempfile.TemporaryDirectory() as folder, patch.object(brain, 'DB', Path(folder)/'knowledge.db'):
            brain.initialize()
            for name, text in fixtures: brain.import_document(name, text.encode())
            correct = 0
            for query, expected in [('ContextTrace advantages', 'contexttrace.txt'), ('tomatoes sunlight', 'gardening.txt'), ('compiler grammar', 'compiler.txt')]:
                hits = brain.keyword_search(query)
                self.assertTrue(hits)
                correct += hits[0]['source'] == expected
                self.assertEqual(hits[0]['page'], 1)
            self.assertEqual(correct, 3, 'Fixture top-1 retrieval must be 3/3. This is not a real-corpus accuracy estimate.')
            self.assertEqual(brain.keyword_search('unfindablequuxxyz'), [])


if __name__ == '__main__':
    unittest.main()
