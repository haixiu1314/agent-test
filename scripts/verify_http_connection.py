"""启动真实 HTTP 协议测试服务器，再经平台 API 验证映射、重试及超时。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from fastapi.testclient import TestClient
from app.main import create_app


class Handler(BaseHTTPRequestHandler):
    retries = 0
    def log_message(self,*args):
        pass

    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path=='/retry':
            Handler.retries+=1
            if Handler.retries==1:
                self.send_response(503);self.end_headers();return
        if self.path=='/timeout':
            time.sleep(0.4)
        if body['payload']['question']!='连接验证' or self.headers.get('X-Fixture')!='fixture-header':
            self.send_response(400);self.end_headers();return
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
        try:
            self.wfile.write(json.dumps({'data':{'answer':'真实 HTTP 协议响应（非 AI）'}}).encode())
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True)
thread.start()
try:
    with TestClient(create_app()) as client:
        credentials={'username':'http_'+uuid4().hex[:12],'password':'http-test-password-123'}
        assert client.post('/api/v1/auth/register',json=credentials).status_code==201
        token=client.post('/api/v1/auth/login',json=credentials).json()['access_token']
        auth={'Authorization':'Bearer '+token}
        project=client.post('/api/v1/projects',headers=auth,json={'name':'HTTP 协议集成验证'}).json()
        checks=[]
        for endpoint,timeout,retries,expected in [('/chat',2,0,True),('/retry',2,1,True),('/timeout',0.1,0,False)]:
            agent=client.post('/api/v1/agents',headers=auth,json={'project_id':project['id'],'name':endpoint,
                'kind':'http','endpoint':f'http://127.0.0.1:{server.server_port}'+endpoint,
                'input_field':'payload.question','history_field':'payload.history','output_field':'data.answer',
                'headers':{'X-Fixture':'fixture-header'},'timeout_seconds':timeout,'retries':retries}).json()
            result=client.post('/api/v1/agents/'+agent['id']+'/test-connection',headers=auth,json={}).json()
            assert result['success']==expected, result
            if endpoint=='/retry':assert result['attempts']==2
            if endpoint=='/timeout':assert result['error_code']=='upstream_timeout'
            checks.append(endpoint)
            assert client.delete('/api/v1/agents/'+agent['id'],headers=auth).status_code==204
        assert client.delete('/api/v1/projects/'+project['id'],headers=auth).status_code==204
        print(json.dumps({'status':'passed','checks':checks,'real_http':True,'fixture_is_ai':False}))
finally:
    server.shutdown();server.server_close()
