import os,json,pathlib,tempfile,fcntl,base64
source=pathlib.Path('/var/lib/chatgpt-mcp-login/.codex/auth.json')
destination=pathlib.Path('/opt/chatgpt-mcp/secrets')
raw=json.loads(source.read_text());tokens=raw.get('tokens',raw)
if not tokens.get('access_token') or not tokens.get('refresh_token'):raise RuntimeError('Independent login did not return complete OAuth credentials.')
existing_file=destination/'auth.json'
if existing_file.exists():
 existing=json.loads(existing_file.read_text());existing=existing.get('tokens',existing)
 def subject(token):
  try:
   claims=json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'==='));identity=claims.get('https://api.openai.com/auth',{})
   return identity.get('chatgpt_user_id') or identity.get('user_id') or claims.get('sub')
  except Exception:return None
 if existing.get('account_id') and tokens.get('account_id')!=existing['account_id']:
  raise RuntimeError('The new login uses a different ChatGPT account/workspace. Existing credentials were not replaced.')
 old_sub=subject(existing.get('access_token',''));new_sub=subject(tokens.get('access_token',''))
 if old_sub and old_sub!=new_sub:raise RuntimeError('The new login belongs to a different user. Existing credentials were not replaced.')
# Only the deployment credential file owns subsequent rotation.
with (destination/'auth.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 fd,tmp=tempfile.mkstemp(dir=destination,prefix='.auth-')
 try:
  with os.fdopen(fd,'w') as stream:
   json.dump({k:tokens[k] for k in ['access_token','refresh_token','account_id','id_token'] if tokens.get(k)},stream);stream.flush();os.fsync(stream.fileno())
  os.chown(tmp,10001,10001);os.replace(tmp,destination/'auth.json')
  directory=os.open(destination,os.O_RDONLY)
  try:os.fsync(directory)
  finally:os.close(directory)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
source.unlink()
print('Independent login installed; duplicate login cache removed. No token values were printed.')
