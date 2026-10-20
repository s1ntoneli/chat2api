import asyncio,json,sys,subprocess
SOCKET=sys.argv[1] if len(sys.argv)>1 else '/opt/chatgpt-mcp/run/server.sock'
CONTAINER=sys.argv[2] if len(sys.argv)>2 else 'chatgpt-mcp-mcp-1'
async def call(reader,writer,method,params=None,ident=1):
 req={'jsonrpc':'2.0','id':ident,'method':method}
 if params is not None:req['params']=params
 writer.write((json.dumps(req)+'\n').encode());await writer.drain()
 while True:
  line=await asyncio.wait_for(reader.readline(),15)
  assert line,'socket closed unexpectedly'
  result=json.loads(line)
  if result.get('id')==ident:
   assert 'error' not in result,(method,result.get('error'))
   return result['result']
async def connect():
 r,w=await asyncio.open_unix_connection(SOCKET)
 await call(r,w,'initialize',dict(protocolVersion='2025-11-25',capabilities={},clientInfo={'name':'shared-process-check','version':'1'}))
 w.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n');await w.drain()
 catalog=await call(r,w,'tools/list',ident=2);assert len(catalog['tools'])==3
 return r,w
async def main():
 clients=await asyncio.gather(*(connect() for _ in range(8)))
 print('8 concurrent Unix MCP clients initialized; overlapping request IDs isolated.',flush=True)
 clients[0][1].close();await clients[0][1].wait_closed()
 r,w=clients[1];assert len((await call(r,w,'tools/list',ident=3))['tools'])==3
 result=await call(r,w,'resources/read',{'uri':'chatgpt://health'},4);assert result['contents']
 rbad,wbad=await asyncio.open_unix_connection(SOCKET);wbad.write(b'not-json\n');await wbad.drain();wbad.close();await wbad.wait_closed()
 assert len((await call(r,w,'tools/list',ident=5))['tools'])==3
 print('Disconnect and malformed-client isolation passed; credential health read passed.',flush=True)
 proc=subprocess.check_output(['docker','top',CONTAINER,'-eo','pid,args'],text=True).splitlines()
 python=[p for p in proc if len(p.split(None,1))==2 and p.split(None,1)[1].startswith('python ')]
 assert len(python)==1,python
 print('Shared container Python process count:',len(python),flush=True)
 print(subprocess.check_output(['docker','stats','--no-stream','--format','{{.MemUsage}}',CONTAINER],text=True).strip(),flush=True)
 for _,writer in clients[1:]:writer.close()
 await asyncio.gather(*(w.wait_closed() for _,w in clients[1:]))
asyncio.run(main())
