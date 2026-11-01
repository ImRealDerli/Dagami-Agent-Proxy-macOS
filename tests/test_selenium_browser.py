import http.server,json,os,signal,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg.selenium_code import SeleniumCodeBrowser
from devproxy_pkg.cli_auth_runtime import run_cli
from devproxy_pkg.auth_manager import AuthSession
from devproxy_pkg.core.profile import ProxyProfile

STATE='s'*22
CODE='4/selenium-fixture-authorization-code'
URL='https://accounts.google.com/o/oauth2/auth?client_id=123456-fixture.apps.googleusercontent.com&state='+STATE+'&code_challenge='+('p'*43)+'&code_challenge_method=S256&redirect_uri=https%3A%2F%2Fantigravity.google%2Foauth-callback&response_type=code&scope=scope1'
BROWSER=Path('/Applications/Brave Browser.app/Contents/MacOS/Brave Browser')

@unittest.skipUnless(sys.platform=='darwin' and BROWSER.is_file(),'Real Brave fixture')
class SeleniumBrowserTests(unittest.TestCase):
    def test_real_selenium_callback_is_submitted_to_waiting_cli(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(('<html><title>Dagami code fixture</title><code id="auth-code">'+CODE+'</code></html>').encode())
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}),patch('devproxy_pkg.auth_manager.load_profile',return_value=ProxyProfile.parse('direct://')):
                root=Path(temp);exe=root/'fixture-cli';result=root/'result.json'
                script='#!'+sys.executable+' -B\nimport json,signal\nsignal.alarm(25)\nfrom pathlib import Path\nprint('+repr(URL)+',flush=True)\nprint("Enter the authorization code:",flush=True)\nvalue=input()\nPath('+repr(str(result))+').write_text(json.dumps({"received":value=='+repr(CODE)+'}))\n'
                exe.write_text(script);exe.chmod(0o700)
                local='http://127.0.0.1:'+str(server.server_port)+'/oauth-callback?state='+STATE+'&code='+CODE
                def captured(session,url):
                    directory=session.hookdir/'fixture-browser';directory.mkdir()
                    args=['--headless=new','--disable-background-networking','--disable-component-update','--disable-gpu','--use-mock-keychain','--user-data-dir='+str(directory),local]
                    watcher=SeleniumCodeBrowser(str(BROWSER),args,dict(os.environ),local,session.code_callback,callback=('http','127.0.0.1',server.server_port,'/oauth-callback'))
                    session.code_browser=watcher;session.browser_processes.append(watcher.process)
                read_in,write_in=os.pipe();read_out,write_out=os.pipe()
                try:
                    with patch.object(AuthSession,'capture_url',captured):code=run_cli(str(exe),'fixture',stdin_fd=read_in,stdout_fd=write_out)
                    self.assertEqual(0,code);self.assertTrue(json.loads(result.read_text())['received'])
                finally:
                    for fd in (read_in,write_in,read_out,write_out):os.close(fd)
        finally:server.shutdown();server.server_close()
