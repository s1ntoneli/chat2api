import argparse,json,urllib.request,urllib.error,http.client
p=argparse.ArgumentParser();p.add_argument('--local-port',type=int);args=p.parse_args()
record=json.load(open('/opt/chatgpt-mcp/auto-oauth-test-tokens.json'))
url=record['resource'];host=url.split('/')[2];token=record['tokens']['access_token']
def rpc(method,params=None,ident=1,auth=token):
 payload={'jsonrpc':'2.0','id':ident,'method':method}
 if params is not None:payload['params']=params
 data=json.dumps(payload).encode();headers={'Host':host,'X-Forwarded-Proto':'https','Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25','User-Agent':'ChatGPT-MCP-Acceptance/1.0'}
 if auth:headers['Authorization']='Bearer '+auth
 if args.local_port:
  c=http.client.HTTPConnection('127.0.0.1',args.local_port,timeout=60);c.request('POST','/mcp',data,headers);r=c.getresponse();status=r.status;body=r.read();c.close()
 else:
  try:r=urllib.request.urlopen(urllib.request.Request(url,data=data,headers=headers),timeout=60)
  except urllib.error.HTTPError as e:r=e
  status=r.code;body=r.read()
 if auth==token:
  assert status==200,('authorized_request_failed',status)
  result=json.loads(body);assert 'error' not in result,('rpc_failed',method)
  return result['result']
 assert status==401,('invalid_token_not_rejected',status)
def unpack(result):
 assert not result.get('isError'), 'tool_call_failed'
 return result.get('structuredContent') or json.loads(next(c['text'] for c in result['content'] if c['type']=='text'))
rpc('initialize',dict(protocolVersion='2025-11-25',capabilities={},clientInfo={'name':'shared-http-check','version':'1'}))
assert len(rpc('tools/list')['tools'])==3
listing=unpack(rpc('tools/call',dict(name='list_conversations',arguments={'limit':2})));assert listing['items']
read=unpack(rpc('tools/call',dict(name='read_conversation',arguments={'conversation_id':listing['items'][0]['id'],'limit':2})));assert read['messages']
rpc('tools/list',auth='')
rpc('tools/list',auth=token[:-8]+'AAAAAAAA')
print(json.dumps(dict(http_mcp_initialize=True,tool_count=3,list_conversations=True,read_conversation=True,unauthenticated_rejected=True,tampered_token_rejected=True)))
