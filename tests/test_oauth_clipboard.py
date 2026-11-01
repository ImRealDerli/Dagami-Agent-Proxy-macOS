import http.server,os,shutil,ssl,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg.auth_manager import validate_clipboard_url,validate_initial_auth_url,auth_urls,AuthSession
from devproxy_pkg.auth_route import verify_route
from devproxy_pkg.core.profile import ProxyProfile

ROOT=Path(__file__).resolve().parents[1]
URL='https://accounts.google.com/o/oauth2/auth?client_id=fixture&state=nonce&redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fcallback'

class ClipboardValidationTests(unittest.TestCase):
    def test_full_local_oauth_is_preserved_and_foreign_callback_or_incomplete_link_rejected(self):
        self.assertEqual(URL,validate_clipboard_url(URL,'antigravity'))
        self.assertEqual(URL,validate_clipboard_url(URL,'agy'))
        for url in ('https://accounts.google.com/login',URL.replace('state=nonce','state='),URL+'&state=other',URL.replace('localhost','evil.example'),URL.replace('accounts.google.com','accounts.google.com.evil.example'),URL.replace('http%3A%2F%2Flocalhost','javascript%3A%2F%2Flocalhost')):
            with self.assertRaises(ValueError):validate_clipboard_url(url,'antigravity')
    def test_intermediate_google_pages_are_not_replayed(self):
        for path in ('/v3/signin/accountchooser','/signin/oauth/v3/consent','/ServiceLogin','/o/oauth2/auth/identifier'):
            intermediate=URL.replace('/o/oauth2/auth',path)
            with self.assertRaisesRegex(ValueError,'промежуточная'):validate_clipboard_url(intermediate,'antigravity')
            with self.assertRaises(ValueError):validate_initial_auth_url(intermediate)
            self.assertEqual([],auth_urls(intermediate,'antigravity'))

    def test_initial_google_versions_preserve_request(self):
        for path in ('/o/oauth2/auth','/o/oauth2/v2/auth'):
            original=URL.replace('/o/oauth2/auth',path)+'&code_challenge=fixture_a%2Bb&code_challenge_method=S256&scope=scope1+scope2'
            self.assertEqual(original,validate_clipboard_url(original,'antigravity'))
            self.assertEqual([original],auth_urls(original,'antigravity'))

    def test_repeated_clipboard_url_opens_once_and_failed_route_can_be_retried(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}),patch('devproxy_pkg.auth_manager.load_profile',return_value=ProxyProfile.parse('direct://')):
            session=AuthSession('agy','fixture',mode='watch')
            try:
                with patch.object(session,'open_url',side_effect=[RuntimeError('HTTP 502'),{'running':True}]) as opened:
                    with self.assertRaises(RuntimeError):session.clipboard_url(URL)
                    session.clipboard_url(URL);session.clipboard_url(URL);self.assertEqual(2,opened.call_count)
            finally:session.close()

class LoginRouteTests(unittest.TestCase):
    def test_connect_failure_explains_profile_and_code_without_oauth_data(self):
        calls=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_CONNECT(self):calls.append(self.path);self.send_error(502)
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with self.assertRaisesRegex(RuntimeError,'broken-profile.*HTTP 502') as error:verify_route('http://127.0.0.1:'+str(server.server_port),URL,'broken-profile')
            self.assertNotIn('nonce',str(error.exception));self.assertEqual(['accounts.google.com:443'],calls)
        finally:server.shutdown();server.server_close();thread.join(timeout=2)
    def test_tls_verification_is_required_on_the_selected_local_tunnel(self):
        with patch('devproxy_pkg.auth_route.http.client.HTTPSConnection') as connect:
            verify_route('http://127.0.0.1:33333',URL,'fixture')
            self.assertEqual(('127.0.0.1',33333),connect.call_args.args)
            self.assertEqual(ssl.CERT_REQUIRED,connect.call_args.kwargs['context'].verify_mode)
            connect.return_value.set_tunnel.assert_called_once_with('accounts.google.com',443)
            connect.return_value.connect.assert_called_once();connect.return_value.close.assert_called_once()

class NativeClipboardTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='darwin' and shutil.which('xcrun'),'AppKit private pasteboard fixture')
    def test_real_appkit_pasteboard_change_detection_ignores_old_and_untrusted_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);runner=root/'Runner.swift';binary=root/'Runner'
            runner.write_text('''import AppKit
import Foundation
@main struct Runner {static func main(){
let board=NSPasteboard.withUniqueName();defer{board.releaseGlobally()}
let watcher=OAuthClipboard(board:board)
let url="'''+URL+'''"
func put(_ value:String){board.clearContents();board.setString(value,forType:.string)}
put(url);assert(watcher.poll(enabled:false,service:"antigravity")==nil)
assert(watcher.poll(enabled:true,service:"antigravity")==nil)
put(url);assert(watcher.poll(enabled:true,service:"antigravity")==url)
assert(watcher.poll(enabled:true,service:"antigravity")==nil)
put(url);assert(watcher.poll(enabled:true,service:"antigravity")==nil)
put("https://evil.example/oauth?client_id=x&state=y");assert(watcher.poll(enabled:true,service:"antigravity")==nil)
put(url.replacingOccurrences(of:"/o/oauth2/auth",with:"/v3/signin/accountchooser"));assert(watcher.poll(enabled:true,service:"antigravity")==nil);assert(!watcher.rejection.isEmpty)
put("password fixture text");assert(watcher.poll(enabled:true,service:"antigravity")==nil)
watcher.reset();put(url);assert(watcher.poll(enabled:true,service:"agy")==url)
print("Private pasteboard: OK")
}}
''')
            subprocess.run(['xcrun','swiftc',str(ROOT/'native/macos/OAuthClipboard.swift'),str(runner),'-o',str(binary)],check=True,capture_output=True,timeout=60)
            subprocess.run([str(binary)],check=True,capture_output=True,timeout=10)
