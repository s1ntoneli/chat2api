import base64,json,tempfile,time,unittest,io
from pathlib import Path
from unittest.mock import patch
import credentials as module

def jwt(exp):
 payload=base64.urlsafe_b64encode(json.dumps({'exp':exp}).encode()).decode().rstrip('=')
 return 'fixture.'+payload+'.signature'

class RefreshTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name);self.file=self.path/'auth.json'
  self.p1=patch.object(module,'AUTH_DIR',self.path);self.p2=patch.object(module,'AUTH_FILE',self.file);self.p1.start();self.p2.start()
 def tearDown(self):
  self.p1.stop();self.p2.stop();self.tmp.cleanup()
 def test_refresh_rotates_atomically_and_preserves_account(self):
  self.file.write_text(json.dumps({'access_token':jwt(time.time()-10),'refresh_token':'fixture-old','account_id':'fixture-account'}))
  fresh=jwt(time.time()+3600)
  with patch.object(module.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps({'access_token':fresh,'refresh_token':'fixture-new'}).encode())):
   result=module.credentials()
  self.assertEqual(result['account_id'],'fixture-account');self.assertEqual(result['refresh_token'],'fixture-new')
  self.assertEqual(json.loads(self.file.read_text()),result);self.assertEqual(self.file.stat().st_mode&0o777,0o600)
 def test_refresh_failure_does_not_corrupt_or_leak(self):
  original=json.dumps({'access_token':jwt(time.time()-10),'refresh_token':'fixture-secret'})
  self.file.write_text(original)
  with patch.object(module.urllib.request,'urlopen',side_effect=OSError('fixture-secret')):
   with self.assertRaisesRegex(RuntimeError,'AUTH_REFRESH_FAILED') as caught:module.credentials()
  self.assertNotIn('fixture-secret',str(caught.exception));self.assertEqual(self.file.read_text(),original)
 def test_valid_access_token_requires_no_refresh(self):
  self.file.write_text(json.dumps({'access_token':jwt(time.time()+3600)}))
  with patch.object(module.urllib.request,'urlopen') as http:module.credentials()
  http.assert_not_called()

if __name__=='__main__':unittest.main()
