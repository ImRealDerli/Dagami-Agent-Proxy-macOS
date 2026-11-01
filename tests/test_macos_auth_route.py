import hashlib,json,os,shutil,struct,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch,Mock
from devproxy_pkg import macos_auth_patch as archive
from devproxy_pkg.auth_manager import AuthSession
from devproxy_pkg.core.profile import ProxyProfile

ROOT=Path(__file__).resolve().parents[1]
URL='https://accounts.google.com/o/oauth2/auth?client_id=fixture&state=a%2Bb&redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fcallback'

def fixture(main=b'"use strict"; const electron_1 = require("electron");require("./languageServer");'):
    files={'package.json':json.dumps({'name':'antigravity','main':'dist/main.js'}).encode(),'dist/main.js':main,'dist/languageServer.js':b'const env = { ...process.env, ...(0, shell_env_1.shellEnvSync)() };if (authMatch) {}','asset.txt':b'original bytes'}
    header={'files':{}};payload=b''
    for name,content in files.items():
        node=header
        parts=name.split('/')
        for part in parts[:-1]:node=node['files'].setdefault(part,{'files':{}})
        node['files'][parts[-1]]={'size':len(content),'offset':str(len(payload))};payload+=content
    encoded=json.dumps(header).encode();body=struct.pack('<I',len(encoded))+encoded+b'\0'*((-len(encoded))%4);pickled=struct.pack('<I',len(body))+body
    return struct.pack('<II',4,len(pickled))+pickled+payload

class ArchiveRouteTests(unittest.TestCase):
    def test_rebuild_preserves_other_files_and_updates_header_and_file_integrity(self):
        original=fixture();changed,expected=archive.rewrite_archive(original,b';"dagami-auth-route-v1";')
        size=struct.unpack_from('<I',changed,12)[0];encoded=changed[16:16+size];header=json.loads(encoded);base=8+struct.unpack_from('<I',changed,4)[0]
        self.assertEqual(expected,hashlib.sha256(encoded).hexdigest())
        entries=header['files']['dist']['files'];entry=entries['main.js'];content=changed[base+int(entry['offset']):base+int(entry['offset'])+entry['size']]
        self.assertIn(archive.MARKER,content);self.assertEqual(hashlib.sha256(content).hexdigest(),entry['integrity']['hash'])
        self.assertIn('integrity',entries['languageServer.js'])
        other=header['files']['asset.txt'];self.assertEqual(b'original bytes',changed[base+int(other['offset']):base+int(other['offset'])+other['size']])
        with self.assertRaises(ValueError):archive.rewrite_archive(changed,b'new hook')
        with self.assertRaises(ValueError):archive.rewrite_archive(fixture(b'unknown'),b'hook')

    @unittest.skipUnless(shutil.which('node'),'Node fixture runner')
    def test_electron_hook_routes_auth_to_owned_loopback_and_other_links_unchanged(self):
        captures=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                captures.append((self.headers.get('Authorization'),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200);self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            script='''const fs=require('fs'),vm=require('vm');let original=[],errors=[];const electron={shell:{openExternal:async u=>original.push(u)},dialog:{showErrorBox:(...a)=>errors.push(a)}};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{require:n=>n==='electron'?electron:require(n),process:{env:{DAGAMI_AUTH_PORT:process.argv[2],DAGAMI_AUTH_TOKEN:'a'.repeat(64)}},URL,Buffer});(async()=>{await Promise.all([electron.shell.openExternal(process.argv[3]),electron.shell.openExternal(process.argv[3])]);await electron.shell.openExternal('https://antigravity.google/docs');if(original.length!==1||errors.length)throw Error('route failed')})().catch(e=>{console.error(e);process.exitCode=1});'''
            subprocess.run(['node','-e',script,str(ROOT/'native/macos/antigravity_auth_hook.js'),str(server.server_port),URL],check=True,capture_output=True,timeout=10)
            self.assertEqual([('Bearer '+'a'*64,{'command':'login','url':URL})],captures)
        finally:server.shutdown();server.server_close();thread.join(timeout=2)

class AuthLifecycleTests(unittest.TestCase):
    def setUp(self):
        route=patch('devproxy_pkg.auth_manager.verify_route');route.start();self.addCleanup(route.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        env=patch.dict(os.environ,{'DEVPROXY_HOME':self.temp.name});env.start();self.addCleanup(env.stop)
        profile=patch('devproxy_pkg.auth_manager.load_profile',return_value=ProxyProfile.parse('direct://'));profile.start();self.addCleanup(profile.stop)
    def session(self,service='codex'):
        s=AuthSession(service,'fixture',mode='watch');self.addCleanup(s.close);return s
    def test_manual_reopen_is_not_silently_deduplicated(self):
        s=self.session();proc=Mock(pid=99999999);proc.poll.return_value=None;proc.wait.side_effect=subprocess.TimeoutExpired('fixture',.3)
        with patch('devproxy_pkg.auth_manager._browser',return_value='/fixture/browser'),patch('devproxy_pkg.auth_manager.Launcher.launch',return_value=proc) as launch:
            s.open_url('https://chatgpt.com/auth/login',manual=True);s.open_url('https://chatgpt.com/auth/login',manual=True)
            self.assertEqual(2,launch.call_count)
        s.browser_processes=[]
    def test_failed_browser_is_not_reported_as_open(self):
        s=self.session();proc=Mock(pid=99999999,returncode=21);proc.poll.return_value=21
        with patch('devproxy_pkg.auth_manager._browser',return_value='/fixture/browser'),patch('devproxy_pkg.auth_manager.Launcher.launch',return_value=proc):
            with self.assertRaisesRegex(RuntimeError,'код 21'):s.open_url('https://chatgpt.com/auth/login')
        s.browser_processes=[]
    def test_antigravity_uses_ide_bridge_and_stop_keeps_ide_running(self):
        s=self.session('antigravity');active={'auth_route':1,'bridge':'http://127.0.0.1:33333','profile':'fixture','url':''}
        with patch('devproxy_pkg.macos_backend.record',return_value={'auth_routing':True,'auth_capture':2}),patch('devproxy_pkg.auth_manager.start_session',return_value=active),patch('devproxy_pkg.auth_manager.request',return_value=active) as request:
            s.start();self.assertTrue(s.attached);self.assertEqual(active['bridge'],s.local)
            s.open_url(URL,manual=True);self.assertIn(unittest.mock.call('antigravity','login',url=URL),request.call_args_list)
            s.close();self.assertFalse(any(c.args[1]=='stop' for c in request.call_args_list if len(c.args)>1))
    def test_old_prepared_ide_requires_explicit_upgrade(self):
        s=self.session('antigravity')
        with patch('devproxy_pkg.macos_backend.record',return_value={}):
            with self.assertRaisesRegex(ValueError,'Настроить вход'):s.start()
    def test_closed_browser_group_does_not_block_tunnel_cleanup(self):
        s=self.session();proc=Mock(pid=99999999);proc.poll.return_value=0;s.browser_processes=[proc]
        with patch('devproxy_pkg.auth_manager.process_alive',return_value=False),patch('devproxy_pkg.auth_manager.signal_group') as signal_group,patch.object(s.tunnel,'stop') as stop:
            s.close();stop.assert_called_once();signal_group.assert_not_called()

class RoutedIdeIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='darwin' and shutil.which('node'),'macOS loopback fixture')
    def test_ide_link_opens_browser_on_exact_same_profile_bridge(self):
        from devproxy_pkg import portable_runtime as runtime
        from devproxy_pkg.core.recovery import StateManager
        import time
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}):
            root=Path(temp);app=root/'fixture-ide';browser=root/'fixture-browser';appout=root/'ide.json';browserout=root/'browser.json'
            app.write_text('#!'+sys.executable+'\nimport os,json,time\nfrom pathlib import Path\nPath('+repr(str(appout))+').write_text(json.dumps({k:os.environ.get(k) for k in ("DAGAMI_AUTH_PORT","DAGAMI_AUTH_TOKEN","HTTP_PROXY")}))\ntime.sleep(60)\n');app.chmod(0o700)
            browser.write_text('#!'+sys.executable+'\nimport os,sys,json,time\nfrom pathlib import Path\nPath('+repr(str(browserout))+').write_text(json.dumps({"proxy":os.environ.get("HTTP_PROXY"),"args":sys.argv[1:]}))\ntime.sleep(60)\n');browser.chmod(0o700)
            StateManager.save_profile(ProxyProfile.parse('direct://',name='fixture').to_dict());runtime.register_executable('antigravity',app)
            errors=[]
            def worker():
                try:runtime.serve_session('antigravity','fixture')
                except Exception as exc:errors.append(exc)
            with patch.object(runtime,'_browser',return_value=str(browser)),patch('devproxy_pkg.auth_route.verify_route'):
                thread=threading.Thread(target=worker,daemon=True);thread.start()
                try:
                    for _ in range(100):
                        if runtime.descriptor('antigravity').exists():break
                        time.sleep(.05)
                    status=runtime.start_session('antigravity','fixture');env=json.loads(appout.read_text())
                    script='''const fs=require('fs'),vm=require('vm');const electron={shell:{openExternal:async()=>{throw Error('Wrong default browser')}},dialog:{showErrorBox:()=>{throw Error('Route failed')}}};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{require:n=>n==='electron'?electron:require(n),process:{env:JSON.parse(process.argv[2])},URL,Buffer});electron.shell.openExternal(process.argv[3]).catch(e=>{console.error(e);process.exitCode=1});'''
                    subprocess.run(['node','-e',script,str(ROOT/'native/macos/antigravity_auth_hook.js'),json.dumps(env),URL],check=True,capture_output=True,timeout=10)
                    routed=json.loads(browserout.read_text());self.assertEqual(status['bridge'],routed['proxy']);self.assertIn('--proxy-server='+status['bridge'],routed['args']);self.assertEqual(URL,routed['args'][-1])
                    with self.assertRaisesRegex(RuntimeError,'промежуточная'):runtime.request('antigravity','login',url=URL.replace('/o/oauth2/auth','/v3/signin/accountchooser'))
                    self.assertNotIn('url',runtime.request('antigravity'));self.assertEqual(URL,runtime.request('antigravity','authStatus')['url'])
                    self.assertNotIn(URL,(runtime.runtime_dir()/'antigravity.log').read_text())
                finally:runtime.request('antigravity','stop');thread.join(timeout=15)
                self.assertFalse(thread.is_alive());self.assertFalse(errors,errors)
