"""Change the sole dedicated MCP login from a JSON object on stdin, without logging credentials."""
import json,os,re,sys,subprocess,time,urllib.request
from pathlib import Path
root=Path('/opt/chatgpt-mcp')
if os.geteuid()!=0:raise SystemExit('Run as root')
change=json.load(sys.stdin);username=change['username'];password=change['password']
if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',username) or len(password)<8:raise SystemExit('Invalid account format')
code='''import json,sys,os
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
p=json.load(sys.stdin)['password'].encode()
k=Argon2id(salt=os.urandom(16),length=32,iterations=3,lanes=4,memory_cost=65536)
sys.stdout.write(k.derive_phc_encoded(p))'''
digest=subprocess.run(['docker','compose','exec','-T','mcp','python','-c',code],cwd=root,input=json.dumps({'password':password}),capture_output=True,text=True,check=True).stdout.strip()
if not digest.startswith('$argon2id$'):raise SystemExit('Password hashing failed')
users_path=root/'auth-config/users.yml';users=json.loads(users_path.read_text())
if len(users['users'])!=1:raise SystemExit('Expected one dedicated login account')
oldname,account=next(iter(users['users'].items()))
account.update(password=digest,displayname=username)
users['users']={username:account}
private_path=root/'private-connection.json';private=json.loads(private_path.read_text());private.update(username=username,password=password)
def atomic(path,data,uid):
 temp=path.with_name(path.name+'.new')
 fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:
  json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())
 os.chown(temp,uid,uid);os.chmod(temp,0o600);os.replace(temp,path)
atomic(users_path,users,10001);atomic(private_path,private,0)
subprocess.run(['docker','compose','restart','authelia'],cwd=root,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
host=private['mcp_url'].split('/')[2]
headers={'Host':host,'X-Forwarded-Proto':'https','X-Forwarded-Host':host,'Content-Type':'application/json','User-Agent':'ChatGPT-MCP-Login-Check/1.0'}
payload=json.dumps(dict(username=username,password=password,keepMeLoggedIn=False,targetURL=private['mcp_url'],requestMethod='GET')).encode()
for attempt in range(12):
 try:
  req=urllib.request.Request('http://127.0.0.1:19091/auth/api/firstfactor',data=payload,headers=headers)
  with urllib.request.urlopen(req,timeout=5) as response:
   result=json.load(response)
  if result.get('status')=='OK':
   print(json.dumps({'username':username,'login_verified':True,'password_stored_as_argon2id':True}));break
  raise RuntimeError('Login verification failed')
 except urllib.error.HTTPError as error:
  raise SystemExit('Login verification failed: HTTP '+str(error.code))
 except (ConnectionError,OSError):
  if attempt==11:raise SystemExit('Login check unavailable; credentials updated, service needs inspection')
  time.sleep(1)
