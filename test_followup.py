import asyncio
import json
import unittest
from types import SimpleNamespace
import aura_followup as followup


class Client:
    def __init__(self,data):
        self.data=data;self.calls=[]
        self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
    async def create(self,**kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.data)))])


class FollowupTests(unittest.TestCase):
    def test_hinglish_followup_rewrite(self):
        c=Client({'query':'ContextTrace ke advantages kya hain?','needs_clarification':False})
        history=[{'role':'user','content':'Uploaded ContextTrace notes ka problem statement samjhao.'},{'role':'assistant','content':'PRIVATE DOCUMENT CONTENT'}]
        result=asyncio.run(followup.resolve_followup(c,'test','Iske advantages?',history,'documents'))
        self.assertEqual(result,'ContextTrace ke advantages kya hain?')
        self.assertNotIn('PRIVATE DOCUMENT CONTENT',json.dumps(c.calls))

    def test_plain_question_no_extra_request(self):
        c=Client({})
        self.assertEqual(asyncio.run(followup.resolve_followup(c,'test','Explain Java interfaces',[],'documents')),'Explain Java interfaces')
        self.assertEqual(c.calls,[])

    def test_general_and_calculator_keep_question(self):
        c=Client({})
        for route in ['general','calculator']:
            self.assertEqual(asyncio.run(followup.resolve_followup(c,'test','more examples',[],route)),'more examples')
        self.assertEqual(c.calls,[])

    def test_ambiguous_topic_asks_clarification(self):
        c=Client({'query':'','needs_clarification':True})
        with self.assertRaises(ValueError):asyncio.run(followup.resolve_followup(c,'test','its benefits',[{'role':'user','content':'Compare two projects'}],'documents'))

    def test_web_excludes_local_document_context(self):
        c=Client({'query':'Latest robotics news examples','needs_clarification':False})
        history=[{'role':'user','content':'Uploaded confidential notes about SecretProject'},{'role':'user','content':'/web latest robotics news'},{'role':'assistant','content':'Private assistant text'}]
        result=asyncio.run(followup.resolve_followup(c,'test','more examples',history,'web'))
        self.assertEqual(result,'Latest robotics news examples')
        self.assertNotIn('SecretProject',json.dumps(c.calls))
        self.assertNotIn('Private assistant text',json.dumps(c.calls))

    def test_web_without_public_topic_does_not_search(self):
        c=Client({})
        with self.assertRaises(ValueError):asyncio.run(followup.resolve_followup(c,'test','iske latest updates',[{'role':'user','content':'my uploaded PDF'}],'web'))
        self.assertEqual(c.calls,[])

    def test_invalid_rewrite_rejected(self):
        for data in [{'query':'hello'}, {'query':99,'needs_clarification':False}, {'query':'','needs_clarification':False}]:
            with self.subTest(data=data),self.assertRaises(ValueError):asyncio.run(followup.resolve_followup(Client(data),'test','iske benefits',[{'role':'user','content':'ContextTrace project'}],'documents'))


if __name__=='__main__':unittest.main()
