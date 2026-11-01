import os,subprocess,tempfile,unittest
from unittest.mock import patch
from devproxy_pkg import journal

class DetailedErrorsTests(unittest.TestCase):
    def test_traceback_command_stderr_and_chained_error_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}):
            try:
                try:raise subprocess.CalledProcessError(1,['codesign','--verify','/fixture/Editor.app'],stderr=b'fixture nested signature invalid\n'+b'x'*5000)
                except subprocess.CalledProcessError as exc:raise RuntimeError('Patch verification failed') from exc
            except Exception as error:journal.record_error('prepare',error)
            text=journal.read();self.assertIn('Traceback',text);self.assertIn('CalledProcessError',text);self.assertIn('Код выхода: 1',text);self.assertIn('nested signature invalid',text);self.assertIn('x'*5000,text)
    def test_full_auth_errors_do_not_store_secrets(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}):
            try:raise RuntimeError('https://accounts.google.ru/accounts/SetSID?sidt=SECRETSESSION https://antigravity.google/oauth-callback?code=SECRETCODE&state=SECRETSTATE password=SECRETPASSWORD Bearer SECRETTOKEN')
            except Exception as error:journal.record_error('authStart',error)
            text=journal.read()
            for secret in ('SECRETSESSION','SECRETCODE','SECRETSTATE','SECRETPASSWORD','SECRETTOKEN'):self.assertNotIn(secret,text)
            self.assertIn('RuntimeError',text)

    def test_quoted_password_with_spaces_is_hidden(self):
        text=journal.clean('password="private multi word value"')
        self.assertNotIn('private',text);self.assertNotIn('multi',text);self.assertNotIn('word',text)
