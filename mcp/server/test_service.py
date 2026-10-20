import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import service

CID='11111111-2222-4333-8444-555555555555'

def node(key, role, text, parent=None, children=None, status='finished_successfully'):
 return {'id':key,'parent':parent,'children':children or [],'message':{'id':key,'author':{'role':role},'content':{'content_type':'text','parts':[text]},'status':status,'recipient':'all'}}

class DeliveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=service.STATE;service.STATE=Path(self.tmp.name)
  self.data={'title':'fixture','current_node':'a0','mapping':{'u0':node('u0','user','first',children=['a0']),'a0':node('a0','assistant','old','u0')}}
  self.posts=0;self.fail_after_send=False;self.pending=False
  self.auth_patch=patch.object(service,'credentials',return_value={'access_token':'fixture'});self.auth_patch.start()
 def tearDown(self):
  self.auth_patch.stop();service.STATE=self.old;self.tmp.cleanup()
 def upstream(self,path,data=None,auth=None):
  if data is None:return copy.deepcopy(self.data)
  self.posts+=1;mid=data['messages'][0]['id'];parent=data['parent_message_id'];self.data['mapping'][parent]['children']=[mid]
  self.data['mapping'][mid]=node(mid,'user',data['messages'][0]['content'],parent,[] if self.pending else ['answer'])
  self.data['current_node']=mid
  if not self.pending:
   self.data['mapping']['answer']=node('answer','assistant','ACK',mid);self.data['current_node']='answer'
  if self.fail_after_send:raise service.UpstreamError('connection dropped after successful write')
  return {}
 def test_saved_reply_and_retry_never_post_twice(self):
  with patch.object(service,'request',side_effect=self.upstream):
   a=service.continue_conversation(CID,'hello','receipt-1',wait_seconds=0)
   b=service.continue_conversation(CID,'hello','receipt-1',wait_seconds=0)
  self.assertEqual(a['status'],'completed');self.assertEqual(a,b);self.assertEqual(self.posts,1)
 def test_failed_response_after_delivery_is_reconciled(self):
  self.fail_after_send=True
  with patch.object(service,'request',side_effect=self.upstream):r=service.continue_conversation(CID,'hello','receipt-2',wait_seconds=0)
  self.assertEqual(r['reply'],'ACK');self.assertEqual(self.posts,1)
 def test_pending_and_restart_do_not_resend(self):
  self.pending=True
  with patch.object(service,'request',side_effect=self.upstream):
   r=service.continue_conversation(CID,'hello','receipt-3',wait_seconds=0)
   self.assertEqual(r['status'],'sent_reply_pending')
   r=service.continue_conversation(CID,'hello','receipt-3',wait_seconds=0)
   self.assertEqual(self.posts,1)
   with self.assertRaisesRegex(RuntimeError,'PREVIOUS_REQUEST_UNRESOLVED'):service.continue_conversation(CID,'next','receipt-4',wait_seconds=0)
 def test_reused_request_id_with_different_message_rejected(self):
  with patch.object(service,'request',side_effect=self.upstream):
   service.continue_conversation(CID,'hello','receipt-5',wait_seconds=0)
   with self.assertRaisesRegex(ValueError,'REQUEST_ID_CONFLICT'):service.continue_conversation(CID,'different','receipt-5',wait_seconds=0)
  self.assertEqual(self.posts,1)
 def test_uncertain_after_crash_is_never_replayed(self):
  def fail(path,data=None,auth=None):
   if data is not None:self.posts+=1;raise service.UpstreamError('network')
   return copy.deepcopy(self.data)
  with patch.object(service,'request',side_effect=fail):
   r=service.continue_conversation(CID,'hello','receipt-6',wait_seconds=0)
   self.assertEqual(r['status'],'delivery_uncertain')
   r=service.continue_conversation(CID,'hello','receipt-6',wait_seconds=0)
  self.assertEqual(self.posts,1)
 def test_active_branch_pagination(self):
  with patch.object(service,'request',side_effect=self.upstream):
   r=service.read_conversation(CID,limit=1)
   self.assertEqual(r['messages'][0]['text'],'old')
   r=service.read_conversation(CID,limit=1,before_message_id=r['next_before_message_id'])
   self.assertEqual(r['messages'][0]['text'],'first')
 def test_external_followup_does_not_become_reply(self):
  self.pending=True
  with patch.object(service,'request',side_effect=self.upstream):
   r=service.continue_conversation(CID,'hello','receipt-7',wait_seconds=0)
   mid=r['user_message_id'];self.data['mapping'][mid]['children']=['external']
   self.data['mapping']['external']=node('external','user','external prompt',mid,['other'])
   self.data['mapping']['other']=node('other','assistant','wrong reply','external')
   r=service.continue_conversation(CID,'hello','receipt-7',wait_seconds=0)
  self.assertEqual(r['status'],'sent_reply_pending')

 def test_terminal_reply_failure_allows_new_message(self):
  self.pending=True
  with patch.object(service,'request',side_effect=self.upstream):
   r=service.continue_conversation(CID,'hello','terminal-1',wait_seconds=0)
   mid=r['user_message_id'];self.data['mapping'][mid]['children']=['failed']
   self.data['mapping']['failed']=node('failed','assistant','',mid,status='finished_partial')
   self.data['current_node']='failed';self.pending=False
   result=service.continue_conversation(CID,'next','terminal-2',wait_seconds=0)
  self.assertEqual(result['status'],'completed');self.assertEqual(self.posts,2)
 def test_auth_failure_before_send_does_not_create_uncertain_receipt(self):
  with patch.object(service,'request',side_effect=self.upstream),patch.object(service,'credentials',side_effect=RuntimeError('AUTH_EXPIRED')):
   with self.assertRaisesRegex(RuntimeError,'AUTH_EXPIRED'):service.continue_conversation(CID,'hello','auth-1',wait_seconds=0)
  with service.db() as connection:self.assertIsNone(connection.execute('SELECT * FROM receipts WHERE request_id=?',('auth-1',)).fetchone())
  self.assertEqual(self.posts,0)

class PreparationTests(DeliveryTests):
 def test_definite_preparation_failure_is_terminal_not_sent(self):
  original=self.upstream
  def rejected(path,data=None,auth=None):
   if data is not None:self.posts+=1;raise service.NotSentError('HTTP_403: upstream_challenge')
   return original(path,data)
  with patch.object(service,'request',side_effect=rejected):
   r=service.continue_conversation(CID,'hello','not-sent-1',wait_seconds=0)
   self.assertEqual(r['status'],'not_sent')
   self.assertEqual(service.continue_conversation(CID,'hello','not-sent-1',wait_seconds=0),r)
  self.assertEqual(self.posts,1)
  with patch.object(service,'request',side_effect=self.upstream):
   self.assertEqual(service.continue_conversation(CID,'hello','not-sent-2',wait_seconds=0)['status'],'completed')

if __name__=='__main__':unittest.main()
