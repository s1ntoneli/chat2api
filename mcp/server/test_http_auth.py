import asyncio,time,unittest
from types import SimpleNamespace
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from http_auth import OIDCTokenVerifier

class TokenBoundaryTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
 def setUp(self):
  self.v=OIDCTokenVerifier('https://example.com/auth','https://example.com/mcp','client','http://unused')
  self.v.keys=SimpleNamespace(get_signing_key_from_jwt=lambda _:SimpleNamespace(key=self.key.public_key()))
  self.claims=dict(iss='https://example.com/auth',aud=['https://example.com/mcp'],sub='owner',client_id='client',exp=int(time.time())+600,iat=int(time.time()),scp=['openid','offline_access'])
 def token(self,claims=None,typ='at+jwt',key=None):return jwt.encode(claims or self.claims,key or self.key,algorithm='RS256',headers={'typ':typ})
 def test_valid_authelia_scp(self):self.assertEqual(self.v._verify(self.token()).scopes,['openid','offline_access'])
 def test_string_scope(self):
  d={**self.claims,'scope':'openid offline_access'};del d['scp'];self.assertIsNotNone(self.v._verify(self.token(d)))
 def test_claim_boundaries(self):
  for change in [dict(iss='https://attacker.test'),dict(aud=['https://other.test/mcp']),dict(client_id='other'),dict(exp=1),dict(iat=int(time.time())+600),dict(scp=['other'])]:
   with self.subTest(change=change):self.assertIsNone(self.v._verify(self.token({**self.claims,**change})))
 def test_missing_required(self):
  for field in ['sub','exp','iat','aud','iss','client_id']:
   d=self.claims.copy();del d[field]
   with self.subTest(field=field):self.assertIsNone(self.v._verify(self.token(d)))
 def test_id_token_and_bad_signature(self):
  self.assertIsNone(self.v._verify(self.token(typ='JWT')))
  key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
  self.assertIsNone(self.v._verify(self.token(key=key)))
 def test_malformed(self):self.assertIsNone(self.v._verify('not-a-jwt'))
if __name__=='__main__':unittest.main()
