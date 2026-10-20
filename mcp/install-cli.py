import urllib.request,json,hashlib,base64,tarfile,io,pathlib
version='0.163.0-linux-x64'
j=json.load(urllib.request.urlopen('https://registry.npmjs.org/@openai/codex/'+version,timeout=30));dist=j['dist']
b=urllib.request.urlopen(dist['tarball'],timeout=120).read()
expected=dist['integrity'].split('sha512-',1)[1].split(' ')[0]
if base64.b64encode(hashlib.sha512(b).digest()).decode()!=expected:raise RuntimeError('package integrity mismatch')
with tarfile.open(fileobj=io.BytesIO(b),mode='r:gz') as tar:
 members=[m for m in tar.getmembers() if m.isfile() and m.name.split('/')[-1]=='codex']
 if len(members)!=1:raise RuntimeError('unexpected package layout: '+str([m.name for m in tar.getmembers()][:20]))
 member=members[0]
 path=pathlib.Path('/opt/chatgpt-mcp/bin');path.mkdir(exist_ok=True)
 binary=path/'codex';binary.write_bytes(tar.extractfile(member).read());binary.chmod(0o755)
print('official_codex_installed_integrity_verified',version)
