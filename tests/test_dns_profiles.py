import os,tempfile,unittest
from unittest.mock import patch
from devproxy_pkg.dns_profile_editor import save_dns_profile
from devproxy_pkg.core.recovery import StateManager
from devproxy_pkg.portable_runtime import load_profile

class DnsProfilesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        item=patch.dict(os.environ,{'DEVPROXY_HOME':self.temp.name});item.start();self.addCleanup(item.stop)
    def test_dns_profile_launches_without_accessing_keychain(self):
        with patch('devproxy_pkg.portable_runtime.SecretStore.get_password',side_effect=AssertionError('must not access Keychain')):
            save_dns_profile('DNS',['https://dns.example/dns-query'])
            profile=load_profile('DNS')
        self.assertTrue(profile.smart_dns);self.assertFalse(profile.proxy_enabled);self.assertEqual('direct',profile.protocol);self.assertIsNone(profile.password)
    def test_switch_to_dns_preserves_disabled_upstream_and_does_not_read_secret(self):
        data={'name':'existing','protocol':'https','host':'proxy.example','port':443,'username':'fixture','requires_password':True,'proxy_enabled':True}
        StateManager.save_profile(data)
        with patch('devproxy_pkg.portable_runtime.SecretStore.get_password',side_effect=AssertionError('must not access Keychain')):
            save_dns_profile('existing',['udp://8.8.8.8'],replace=True);profile=load_profile('existing')
        self.assertEqual('proxy.example',profile.host);self.assertFalse(profile.proxy_enabled);self.assertTrue(StateManager.get_profile('existing')['requires_password'])
    def test_invalid_dns_keeps_existing_profile(self):
        save_dns_profile('DNS',['udp://8.8.8.8']);old=StateManager.get_profile('DNS')
        with self.assertRaises(ValueError):save_dns_profile('DNS',['file:///tmp/invalid'],replace=True)
        self.assertEqual(old,StateManager.get_profile('DNS'))
    def test_duplicate_is_not_overwritten_without_confirmation(self):
        save_dns_profile('DNS',['udp://8.8.8.8'])
        with self.assertRaises(ValueError):save_dns_profile('DNS',['udp://1.1.1.1'])
        self.assertEqual(['udp://8.8.8.8'],StateManager.get_profile('DNS')['dns_endpoints'])

class AiScopeTests(unittest.TestCase):
    def test_ai_services_and_subdomains_use_smart_dns(self):
        from devproxy_pkg.core.smart_dns import scoped
        for host in ('api.openai.com','chatgpt.com','api.anthropic.com','claude.ai','chat.deepseek.com','chat.qwen.ai','grok.com','api.perplexity.ai','api.mistral.ai','aistudio.google.com'):
            self.assertTrue(scoped(host,True,'ai'),host)
        self.assertFalse(scoped('openai.com.evil.example',True,'ai'))
        self.assertFalse(scoped('notopenai.com',True,'ai'))
        self.assertFalse(scoped('accounts.google.com',True,'ai'))
    def test_custom_domains_have_exact_or_explicit_wildcard_matching(self):
        from devproxy_pkg.core.smart_dns import scoped,validate_domains
        domains=validate_domains(['example.ai','*.custom.example'])
        self.assertTrue(scoped('example.ai',True,'ai',domains))
        self.assertFalse(scoped('other.example.ai',True,'ai',domains))
        self.assertTrue(scoped('api.custom.example',True,'ai',domains))
        with self.assertRaises(ValueError):validate_domains(['https://example.ai/path'])
    def test_scope_and_custom_domains_survive_profile_roundtrip(self):
        from devproxy_pkg.core.profile import ProxyProfile
        p=ProxyProfile.parse('direct://');p.dns_scope='ai';p.dns_domains=['*.example.ai']
        saved=ProxyProfile.from_dict(p.to_dict())
        self.assertEqual('ai',saved.dns_scope);self.assertEqual(['*.example.ai'],saved.dns_domains)
