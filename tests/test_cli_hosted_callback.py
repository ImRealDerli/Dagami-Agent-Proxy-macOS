from pathlib import Path
import unittest
from urllib.parse import urlsplit,parse_qs
from devproxy_pkg.auth_manager import validate_clipboard_url
from devproxy_pkg.cli_auth_runtime import cli_auth_urls,complete_cli_oauth

FRAME=(Path(__file__).parent/'fixtures/agy_hosted_oauth.txt').read_text()
URL=''.join(line.strip() for line in FRAME.splitlines())

class HostedCallbackTests(unittest.TestCase):
    def test_actual_cli_wrapped_layout_preserves_official_callback_and_all_parameters(self):
        self.assertEqual([URL],cli_auth_urls(FRAME,settled=True))
        self.assertEqual(URL,validate_clipboard_url(URL,'agy'));self.assertTrue(complete_cli_oauth(URL))
        query=parse_qs(urlsplit(URL).query)
        self.assertEqual(['https://antigravity.google/oauth-callback'],query['redirect_uri'])
        self.assertEqual(['s'*22],query['state']);self.assertEqual(['p'*43],query['code_challenge'])
    def test_hosted_callback_does_not_expand_ide_callback_rules(self):
        with self.assertRaises(ValueError):validate_clipboard_url(URL,'antigravity')
    def test_lookalike_hosts_paths_and_protocols_are_rejected(self):
        from urllib.parse import quote
        old=quote('https://antigravity.google/oauth-callback',safe='')
        for callback in ('https://antigravity.google.evil.example/oauth-callback','https://evil.example/oauth-callback','http://antigravity.google/oauth-callback','https://antigravity.google:8443/oauth-callback','https://antigravity.google/other','https://antigravity.google/oauth-callback?next=evil','https://antigravity.google/oauth-callback#evil','https://user@antigravity.google/oauth-callback'):
            candidate=URL.replace(old,quote(callback,safe=''))
            self.assertNotEqual(URL,candidate)
            with self.assertRaises(ValueError):validate_clipboard_url(candidate,'agy')
            self.assertFalse(complete_cli_oauth(candidate))
