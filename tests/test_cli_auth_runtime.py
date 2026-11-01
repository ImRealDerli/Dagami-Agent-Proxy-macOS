import json,os,pty,subprocess,sys,tempfile,termios,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg.cli_auth_runtime import run_cli,cli_auth_urls,complete_cli_oauth
from devproxy_pkg.auth_manager import AuthSession
from devproxy_pkg.core.profile import ProxyProfile

URL='https://accounts.google.com/o/oauth2/auth?access_type=offline&client_id=123456-fixture.apps.googleusercontent.com&code_challenge='+('p'*43)+'&code_challenge_method=S256&redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fcallback&response_type=code&scope=scope1+scope2&state='+('n'*22)

@unittest.skipUnless(sys.platform=='darwin','macOS controlling PTY fixture')
class CliCaptureTests(unittest.TestCase):
    def run_fixture(self,browser_hook=False,tty_input=False,wrapped=False):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}),patch('devproxy_pkg.auth_manager.load_profile',return_value=ProxyProfile.parse('direct://')):
            root=Path(temp);marker=root/'captured';evidence=root/'env.json';exe=root/'fixture-agy'
            code='#!'+sys.executable+'\nimport os,sys,json,time,subprocess\nfrom pathlib import Path\n'
            code+='ttyfd=os.open("/dev/tty",os.O_RDWR);os.close(ttyfd)\n'
            code+='Path('+repr(str(evidence))+').write_text(json.dumps({"tty":os.isatty(0),"proxy":os.environ.get("HTTP_PROXY"),"https":os.environ.get("HTTPS_PROXY"),"host":os.environ.get("ANTIGRAVITY_VSCODE_HOST"),"args":sys.argv[1:]}))\n'
            if browser_hook:code+='subprocess.run([os.environ["BROWSER"],'+repr(URL)+'],check=True)\n'
            elif wrapped:code+='os.write(1,'+repr(('\n'.join('│ '+URL[i:i+60]+' │' for i in range(0,len(URL),60))+'\n\n').encode())+')\n'
            else:code+='os.write(1,b"ANTIGRAVITY_OPEN_URL: ");os.write(1,'+repr(URL[:70].encode())+');time.sleep(.05);os.write(1,'+repr((URL[70:]+'\n').encode())+')\n'
            code+='deadline=time.monotonic()+5\nwhile not Path('+repr(str(marker))+').exists() and time.monotonic()<deadline:time.sleep(.02)\n'
            code+='print("INPUT="+sys.stdin.readline().strip(),flush=True)\nraise SystemExit(7)\n'
            exe.write_text(code);exe.chmod(0o700);captured=[]
            def capture(session,url):captured.append((url,session.local));marker.write_text('done')
            if tty_input:
                write_input,read_input=pty.openpty();terminal_before=termios.tcgetattr(read_input)
            else:read_input,write_input=os.pipe()
            read_output,write_output=os.pipe()
            try:
                if tty_input:
                    def feed():
                        deadline=time.monotonic()+6
                        while not marker.exists() and time.monotonic()<deadline:time.sleep(.02)
                        time.sleep(.05);os.write(write_input,b'hello-cli\n')
                    feeder=threading.Thread(target=feed);feeder.start()
                else:os.write(write_input,b'hello-cli\n');os.close(write_input);write_input=None
                with patch.object(AuthSession,'capture_url',capture):result=run_cli(str(exe),'fixture',['--fixture-argument'],stdin_fd=read_input,stdout_fd=write_output)
                if tty_input:
                    feeder.join(timeout=2);after=termios.tcgetattr(read_input);terminal_before[3]&=~getattr(termios,"PENDIN",0);after[3]&=~getattr(termios,"PENDIN",0);self.assertEqual(terminal_before,after)
                os.close(write_output);write_output=None;output=os.read(read_output,65536).decode(errors='replace')
                info=json.loads(evidence.read_text());self.assertEqual(7,result);self.assertTrue(info['tty']);self.assertEqual('1',info['host']);self.assertEqual(['--fixture-argument'],info['args'])
                self.assertEqual([(URL,info['proxy'])],captured);self.assertEqual(info['proxy'],info['https']);self.assertIn('INPUT=hello-cli',output)
                self.assertFalse(list((root/'sessions').glob('auth-hook-*')))
            finally:
                for fd in (read_input,write_input,read_output,write_output):
                    if fd is not None:os.close(fd)
    def test_cli_output_url_is_intercepted_with_exact_proxy_and_interactive_stdin(self):self.run_fixture()
    def test_cli_browser_hook_uses_same_authenticated_loopback_capture(self):self.run_fixture(True)
    def test_wrapped_cli_url_is_reassembled_before_capture(self):self.run_fixture(wrapped=True)
    def test_real_terminal_input_mode_is_restored_after_cli_exit(self):self.run_fixture(tty_input=True)

    def test_launch_failure_closes_tunnel_and_capture_resources(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}),patch('devproxy_pkg.auth_manager.load_profile',return_value=ProxyProfile.parse('direct://')):
            with patch('devproxy_pkg.cli_auth_runtime.Launcher.launch',side_effect=OSError('fixture spawn denied')):
                with self.assertRaisesRegex(OSError,'fixture spawn denied'):run_cli('/fixture/agy','fixture',stdin_fd=0,stdout_fd=1)
            self.assertFalse(list((Path(temp)/'sessions').glob('auth-hook-*')))

class WrappedLinkTests(unittest.TestCase):
    def test_partial_client_id_is_never_opened(self):
        partial='https://accounts.google.com/o/oauth2/auth?access_type=offline&client_id=123456'
        self.assertFalse(complete_cli_oauth(partial));self.assertEqual([],cli_auth_urls(partial+'\n',settled=True))
    def test_wraps_ansi_and_split_percent_escape_preserve_all_oauth_bytes(self):
        for width in (40,60,80,120):
            lines=['│ '+URL[i:i+width]+' │' for i in range(0,len(URL),width)]
            framed='\x1b[32m'+'\n'.join(lines)+'\x1b[0m\n\n'
            self.assertEqual([URL],cli_auth_urls(framed))
            self.assertEqual([],cli_auth_urls(lines[0]+'\n',settled=True))
    def test_full_single_line_waits_for_completion_and_then_opens_once(self):
        self.assertEqual([],cli_auth_urls(URL+'\n'))
        self.assertEqual([URL],cli_auth_urls(URL+'\n',settled=True))
        self.assertFalse(complete_cli_oauth(URL.replace('p'*43,'p'*20)))
