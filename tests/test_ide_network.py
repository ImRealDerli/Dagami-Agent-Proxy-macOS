import http.server,json,os,shutil,socket,ssl,subprocess,tempfile,threading,time,unittest
from pathlib import Path
from devproxy_pkg.core.profile import ProxyProfile
from devproxy_pkg.core.tunnel import LocalTunnel


@unittest.skipUnless(shutil.which('node') and shutil.which('openssl'),'Node and OpenSSL fixture')
class IDENetworkTests(unittest.TestCase):
    def test_tls_redirect_abort_and_oauth_handoff_use_only_local_bridge(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cert=root/'cert.pem';key=root/'key.pem'
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],check=True,capture_output=True)
            received=[];posts=[]
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_GET(self):
                    received.append(self.path)
                    if self.path=='/redirect':self.send_response(302);self.send_header('Location','/manifest');self.end_headers();return
                    if self.path=='/slow':time.sleep(.15)
                    body=b'{"fixture":true}'
                    try:self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
                    except OSError:pass
                def do_POST(self):
                    posts.append((self.headers.get('Authorization'),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                    self.send_response(200);self.end_headers()
            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key);server.socket=context.wrap_socket(server.socket,server_side=True)
            auth=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
            for item in (server,auth):threading.Thread(target=item.serve_forever,daemon=True).start()
            tunnel=LocalTunnel(ProxyProfile.parse('direct://'));connections=[];original=tunnel._handle_client
            def observed(client):connections.append(1);return original(client)
            tunnel._handle_client=observed;port=tunnel.start()
            blocked=socket.socket();blocked.bind(('127.0.0.1',0))
            helper=Path(__file__).resolve().parents[1]/'native/macos/ide_network.cjs'
            env=dict(os.environ,DAGAMI_IDE_PROXY='http://127.0.0.1:'+str(port),NODE_EXTRA_CA_CERTS=str(cert),DAGAMI_AUTH_PORT=str(auth.server_port),DAGAMI_AUTH_TOKEN='f'*32,DAGAMI_DEAD_PROXY='http://127.0.0.1:'+str(blocked.getsockname()[1]))
            base='https://localhost:'+str(server.server_port)
            script='''const assert=require('node:assert/strict'),net=require(process.argv[1]);(async()=>{
const response=await net.fetch(process.argv[2]+'/redirect');assert.equal((await response.json()).fixture,true);
await assert.rejects(net.fetch(process.argv[2]+'/slow',{signal:AbortSignal.timeout(20)}));
let original=0;await net.openExternal(()=>{original++;return true},'https://example.test/');assert.equal(original,1);
await net.openExternal(()=>{throw Error('Original OAuth opener must not run')},'https://accounts.google.com/o/oauth2/auth?client_id=fixture&state=fixture-state&redirect_uri=http%3A%2F%2Flocalhost%3A12345');
process.env.DAGAMI_IDE_PROXY=process.env.DAGAMI_DEAD_PROXY;await assert.rejects(net.fetch(process.argv[2]+'/manifest'));
console.log('FIXTURE OK');})().catch(e=>{console.error(e.message);process.exitCode=1});'''
            try:
                result=subprocess.run(['node','-e',script,str(helper),base],env=env,capture_output=True,text=True,timeout=15)
                self.assertEqual(0,result.returncode,result.stderr);self.assertIn('FIXTURE OK',result.stdout)
                self.assertGreaterEqual(len(connections),2);self.assertIn('/manifest',received);self.assertEqual('Bearer '+'f'*32,posts[0][0]);self.assertEqual('login',posts[0][1]['command'])
                untrusted=dict(env);untrusted.pop('NODE_EXTRA_CA_CERTS',None)
                script="require(process.argv[1]).fetch(process.argv[2]+'/manifest').then(()=>process.exitCode=1).catch(e=>{if(!/certificate|self.signed/i.test(e.message))process.exitCode=2})"
                result=subprocess.run(['node','-e',script,str(helper),base],env=untrusted,capture_output=True,text=True,timeout=10)
                self.assertEqual(0,result.returncode,result.stderr)
            finally:blocked.close();tunnel.stop();server.shutdown();server.server_close();auth.shutdown();auth.server_close()
