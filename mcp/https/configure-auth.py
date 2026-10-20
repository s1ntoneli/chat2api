from pathlib import Path
import subprocess,json,secrets,os,re
root=Path('/opt/chatgpt-mcp');cfg=root/'auth-config';data=root/'auth-data'
for p in [cfg,data]:p.mkdir(exist_ok=True);p.chmod(0o700);os.chown(p,10001,10001)
private=root/'private-connection.json'
if private.exists():raise RuntimeError('Auth already provisioned; refusing to rotate existing passwords.')
def generate(kind,length):
 r=subprocess.run(['docker','run','--rm','authelia/authelia:4.39.28','authelia','crypto','hash','generate',kind,'--random','--random.length',str(length)],capture_output=True,text=True,check=True)
 lines=r.stdout.splitlines();found={}
 for line in lines:
  if ':' in line:
   key,val=line.split(':',1);found[key.strip().lower()]=val.strip()
 password=next((v for k,v in found.items() if 'password' in k),None)
 digest=next((v for k,v in found.items() if 'digest' in k),None)
 if not password or not digest:raise RuntimeError('Unexpected hash CLI fields: '+str(list(found)))
 return password,digest
password,password_digest=generate('argon2',32)
client_secret,client_digest=generate('pbkdf2',48)
key=subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072'],capture_output=True,text=True,check=True).stdout
host=os.environ['PUBLIC_HOST'];origin='https://'+host;issuer=origin+'/auth';resource=origin+'/mcp'
config={
 'server':{'address':'tcp://0.0.0.0:9091/auth','disable_healthcheck':True},
 'log':{'level':'info','format':'json'},
 'authentication_backend':{'password_reset':{'disable':True},'file':{'path':'/config/users.yml'}},
 'access_control':{'default_policy':'deny','rules':[{'domain':host,'policy':'one_factor'}]},
 'session':{'secret':secrets.token_hex(32),'cookies':[{'domain':host,'authelia_url':issuer,'default_redirection_url':origin+'/'}]},
 'storage':{'encryption_key':secrets.token_hex(32),'local':{'path':'/data/db.sqlite3'}},
 'notifier':{'filesystem':{'filename':'/data/notifications.txt'}},
 'totp':{'disable':True},'webauthn':{'disable':True},
 'identity_providers':{'oidc':{'hmac_secret':secrets.token_hex(32),
   'jwks':[{'key_id':'chatgpt-mcp-20261020','algorithm':'RS256','use':'sig','key':key}],
   'lifespans':{'access_token':'1h','refresh_token':'30d','authorize_code':'1m','id_token':'1h'},
   'clients':[{'client_id':'chatgpt-mcp','client_name':'ChatGPT Conversations',
      'client_secret':client_digest,'public':False,'authorization_policy':'one_factor',
      'redirect_uris':[origin+'/oauth/callback'],
      'grant_types':['authorization_code','refresh_token'],'response_types':['code'],'response_modes':['query'],
      'scopes':['openid','offline_access'],'audience':[resource],'requested_audience_mode':'explicit',
      'require_pkce':True,'pkce_challenge_method':'S256','token_endpoint_auth_method':'client_secret_post',
      'access_token_signed_response_alg':'RS256','consent_mode':'explicit'}]}}
}
users={'users':{'owner':{'disabled':False,'displayname':'Owner','password':password_digest,'groups':['owner']}}}
for name,obj in [('configuration.yml',config),('users.yml',users)]:
 p=cfg/name;p.write_text(json.dumps(obj,indent=2));p.chmod(0o600);os.chown(p,10001,10001)
private.write_text(json.dumps({'mcp_url':resource,'authentication':'OAuth','client_registration':'internal upstream client (not entered in ChatGPT)',
 'client_id':'chatgpt-mcp','client_secret':client_secret,'scopes':'openid offline_access',
 'login_url':issuer+'/','username':'owner','password':password},indent=2));private.chmod(0o600)
for name in ['secrets','state','run']:
 p=root/name;p.mkdir(exist_ok=True);p.chmod(0o700);os.chown(p,10001,10001)
p=root/'secrets/proxy-auth.json'
p.write_text(json.dumps({'client_id':'chatgpt-mcp','client_secret':client_secret,'signing_key':secrets.token_urlsafe(48)}))
p.chmod(0o600);os.chown(p,10001,10001)
print('Authelia config and dedicated credentials provisioned; no secrets printed.')
