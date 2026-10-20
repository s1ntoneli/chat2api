import asyncio,json,os
async def client():
 p=await asyncio.create_subprocess_exec('ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',os.environ['MCP_SSH_HOST'],os.environ.get('MCP_REMOTE_COMMAND','/opt/chatgpt-mcp/mcp-stdio'),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
 async def call(method,params=None,ident=1):
  q={'jsonrpc':'2.0','method':method,'id':ident}
  if params is not None:q['params']=params
  p.stdin.write((json.dumps(q)+'\n').encode());await p.stdin.drain()
  while True:
   line=await asyncio.wait_for(p.stdout.readline(),15);assert line,'SSH stream closed'
   x=json.loads(line)
   if x.get('id')==ident:
    assert 'error' not in x;return x['result']
 await call('initialize',dict(protocolVersion='2025-11-25',capabilities={},clientInfo={'name':'ssh-shared-check','version':'1'}))
 p.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n');await p.stdin.drain()
 assert len((await call('tools/list',ident=2))['tools'])==3
 assert (await call('resources/read',{'uri':'chatgpt://health'},3))['contents']
 p.stdin.close();await asyncio.wait_for(p.wait(),10);assert p.returncode==0
 return True
async def main():
 assert all(await asyncio.gather(client(),client()))
 print('Two concurrent SSH stdio clients passed initialize/tools/health and clean disconnect using socat.')
asyncio.run(main())
