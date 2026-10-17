"""No API keys or network calls; deterministic router and stream tests."""
import asyncio
import contextlib
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import aura_router as router


class Stream:
    def __init__(self):self.closed=False
    def __aiter__(self):
        async def generate():
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='Test answer'))])
        return generate()
    async def close(self):self.closed=True


class Client:
    def __init__(self,route='general',expression=''):
        self.route=route;self.expression=expression;self.calls=[];self.stream=Stream()
        self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
    async def create(self,**kwargs):
        self.calls.append(kwargs)
        if kwargs.get('tools'):
            function=SimpleNamespace(name='route_request',arguments=json.dumps({'route':self.route,'expression':self.expression}))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[SimpleNamespace(function=function)]))])
        return self.stream


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.brain=SimpleNamespace(documents=lambda:[{'name':'project.pdf'}],build_prompt=lambda *a:'DOCUMENT EVIDENCE: calibration threshold is 73 percent')
        self.heart=SimpleNamespace(heart_prompt=lambda:'HEART STYLE ')
        self.web=SimpleNamespace(web_reply=AsyncMock(return_value='Research with links'))
        self.modules=patch.dict(sys.modules,{'aura_brain':self.brain,'aura_heart':self.heart,'aura_web':self.web})
        self.modules.start()

    def tearDown(self):self.modules.stop()

    def test_basic_decimal_arithmetic(self):
        for expression,expected in [('0.1+0.2','0.3'),('18% of 2500','450'),('2^8','256'),('sqrt(81)','9'),('abs(-7)','7'),('7%3','1'),('10/4','2.5')]:
            with self.subTest(expression=expression):self.assertEqual(router.calculate(expression),expected)

    def test_reject_code_and_excessive_arithmetic(self):
        for expression in ["__import__('os').system('whoami')",'(1).__class__','[x for x in [1]]','1/0','2**10000','sqrt(-1)','9'*257]:
            with self.subTest(expression=expression),self.assertRaises(ValueError):router.calculate(expression)

    def test_manual_commands(self):
        for command,route in [('/web news','web'),('/docs notes','documents'),('/calc 2+2','calculator'),('/chat hello','general')]:
            self.assertEqual(router.direct_route(command)['route'],route)
        with self.assertRaises(ValueError):router.direct_route('/web')
        self.assertIsNone(router.direct_route('Explain databases'))

    def test_direct_arithmetic_no_model_call(self):
        client=Client()
        plan=asyncio.run(router.choose_route(client,'test','What is 12 * 7?',[]))
        self.assertEqual(plan['route'],'calculator');self.assertEqual(client.calls,[])

    def test_model_selects_each_route(self):
        for route in router.ROUTES:
            client=Client(route,'25*4' if route=='calculator' else '')
            plan=asyncio.run(router.choose_route(client,'test','Natural language request',[]))
            self.assertEqual(plan['route'],route)
            self.assertEqual(client.calls[0]['tool_choice']['function']['name'],'route_request')

    def test_unknown_tool_route_rejected(self):
        with self.assertRaises(ValueError):asyncio.run(router.choose_route(Client('shell'),'test','Run arbitrary tools',[]))

    def collect(self,client,user):
        async def run():return [x async for x in router.route_stream(client,'test',user,[],'LOCAL_PRIVATE_PREFERENCE')]
        return asyncio.run(run())

    def test_calculator_stream(self):
        client=Client();events=self.collect(client,'/calc 15*6')
        self.assertEqual(events[0]['name'],'calculator');self.assertEqual(events[1],{'type':'token','text':'15*6 = 90'})
        self.assertEqual(client.calls,[])

    def test_general_stream_closes(self):
        client=Client();events=self.collect(client,'/chat Explain stacks')
        self.assertEqual(events[0]['name'],'general')
        self.assertIn('HEART STYLE',client.calls[-1]['messages'][0]['content'])
        self.assertTrue(client.stream.closed)

    def test_documents_stream_uses_evidence(self):
        client=Client();events=self.collect(client,'/docs What is the threshold?')
        self.assertEqual(events[0]['name'],'documents')
        self.assertIn('73 percent',client.calls[-1]['messages'][0]['content'])

    def test_web_receives_only_current_question(self):
        client=Client('web');events=self.collect(client,'Latest robotics news')
        self.assertEqual(events[0]['name'],'web')
        self.web.web_reply.assert_awaited_once_with(client,'test','Latest robotics news')
        self.assertNotIn('LOCAL_PRIVATE_PREFERENCE',repr(self.web.web_reply.call_args))

    def test_early_close_closes_model_stream(self):
        client=Client()
        async def run():
            async with contextlib.aclosing(router.route_stream(client,'test','/chat hello',[],'')) as stream:
                await anext(stream)
                await anext(stream)
        asyncio.run(run());self.assertTrue(client.stream.closed)


if __name__=='__main__':unittest.main()
