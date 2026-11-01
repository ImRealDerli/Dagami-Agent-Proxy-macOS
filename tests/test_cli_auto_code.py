import json,os,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg.cli_code_gate import CliCodeGate
from devproxy_pkg.selenium_code import callback_code,CALLBACK
from devproxy_pkg.cli_auth_runtime import run_cli
from devproxy_pkg.auth_manager import AuthSession
from devproxy_pkg.core.profile import ProxyProfile

STATE='s'*22
CODE='4/fixture-authorization-code'
URL='https://accounts.google.com/o/oauth2/auth?client_id=123456-fixture.apps.googleusercontent.com&state='+STATE+'&code_challenge='+('p'*43)+'&code_challenge_method=S256&redirect_uri=https%3A%2F%2Fantigravity.google%2Foauth-callback&response_type=code&scope=scope1'
CALLBACK_URL='https://antigravity.google/oauth-callback?state='+STATE+'&code='+CODE

class CodeGateTests(unittest.TestCase):
    def test_only_matching_state_after_prompt_is_submitted_once(self):
        gate=CliCodeGate();gate.begin(URL);self.assertFalse(gate.offer(CODE,'wrong'));self.assertTrue(gate.offer(CODE,STATE));self.assertIsNone(gate.take())
        gate.observe('Enter the authorization code:');self.assertEqual(CODE,gate.take());self.assertIsNone(gate.take());self.assertFalse(gate.offer(CODE,STATE))
    def test_manual_input_prevents_overwriting(self):
        gate=CliCodeGate();gate.begin(URL);gate.observe('Paste the authorization code here:');gate.user_input();gate.offer(CODE,STATE);self.assertIsNone(gate.take())
    def test_callback_host_state_and_control_characters_are_checked(self):
        self.assertEqual(CODE,callback_code(CALLBACK_URL,STATE))
        for url in (CALLBACK_URL.replace('antigravity.google','antigravity.google.evil.example'),CALLBACK_URL.replace('https:','http:'),CALLBACK_URL.replace(STATE,'wrong'),CALLBACK_URL+'&state=other',CALLBACK_URL.replace('oauth-callback','elsewhere'),CALLBACK_URL.replace(CODE,'bad%0Acommand')):
            self.assertIsNone(callback_code(url,STATE))

    def test_terminal_reports_and_focus_are_not_manual_input(self):
        gate=CliCodeGate();gate.begin(URL);gate.observe('Paste the authorization code below:')
        for data in (b'\x1b[I',b'\x1b[O',b'\x1b[12;',b'34R',b'\x1b[?1;2c',b'\x1b]11;rgb:0000/0000/0000\x07'):
            self.assertFalse(gate.user_input(data))
        self.assertFalse(gate.manual);gate.offer(CODE,STATE);self.assertEqual(CODE,gate.take())
        gate.observe('Paste the authorization code below:');self.assertFalse(gate.waiting)

    def test_escape_cancel_blocks_automatic_submission(self):
        gate=CliCodeGate();gate.begin(URL);gate.observe('Enter the authorization code:')
        self.assertTrue(gate.user_input(b'\x1b'));gate.offer(CODE,STATE);self.assertIsNone(gate.take())

    def test_real_keys_still_block_injection_after_terminal_reports(self):
        gate=CliCodeGate();gate.begin(URL);gate.observe('Enter the authorization code:')
        self.assertTrue(gate.user_input(b'\x1b[Iuser text'));gate.offer(CODE,STATE);self.assertIsNone(gate.take())

@unittest.skipUnless(sys.platform=='darwin','PTY fixture')
class CodeSubmissionTests(unittest.TestCase):
    def test_browser_code_reaches_waiting_cli_with_enter_without_user_typing(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}),patch('devproxy_pkg.auth_manager.load_profile',return_value=ProxyProfile.parse('direct://')):
            root=Path(temp);exe=root/'fixture-cli';marker=root/'browser-done';result=root/'result.json'
            script='#!'+sys.executable+' -B\nimport os,json,time\nfrom pathlib import Path\n'
            script+='print('+repr(URL)+',flush=True)\nwhile not Path('+repr(str(marker))+').exists():time.sleep(.02)\nprint("Enter the authorization code:",flush=True)\nvalue=input()\nPath('+repr(str(result))+').write_text(json.dumps({"received":value=='+repr(CODE)+'}))\n'
            exe.write_text(script);exe.chmod(0o700)
            def captured(session,url):session.code_callback(CODE,STATE);marker.write_text('done')
            read_in,write_in=os.pipe();read_out,write_out=os.pipe()
            try:
                with patch.object(AuthSession,'capture_url',captured):code=run_cli(str(exe),'fixture',stdin_fd=read_in,stdout_fd=write_out)
                self.assertEqual(0,code);self.assertTrue(json.loads(result.read_text())['received'])
            finally:
                for fd in (read_in,write_in,read_out,write_out):os.close(fd)

    def test_focus_return_does_not_block_code_in_real_raw_pty(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}),patch('devproxy_pkg.auth_manager.load_profile',return_value=ProxyProfile.parse('direct://')):
            root=Path(temp);exe=root/'raw-cli';result=root/'result.json'
            script='#!'+sys.executable+' -B\nimport os,tty,signal,re,json\nfrom pathlib import Path\nsignal.alarm(10)\ntty.setraw(0)\nprint('+repr(URL)+',flush=True)\nprint("Paste the authorization code below:",flush=True)\nvalue=b""\nwhile b"\\r" not in value:value+=os.read(0,4096)\nvalue=re.sub(rb"\\x1b\\[[IO]",b"",value).split(b"\\r")[0]\nPath('+repr(str(result))+').write_text(json.dumps({"received":value.decode()=='+repr(CODE)+'}))\n'
            exe.write_text(script);exe.chmod(0o700)
            read_in,write_in=os.pipe();read_out,write_out=os.pipe()
            def captured(session,url):
                time.sleep(.2);os.write(write_in,b'\x1b[I');time.sleep(.15);session.code_callback(CODE,STATE)
            try:
                with patch.object(AuthSession,'capture_url',captured):code=run_cli(str(exe),'fixture',stdin_fd=read_in,stdout_fd=write_out)
                self.assertEqual(0,code);self.assertTrue(json.loads(result.read_text())['received'])
            finally:
                for fd in (read_in,write_in,read_out,write_out):os.close(fd)
