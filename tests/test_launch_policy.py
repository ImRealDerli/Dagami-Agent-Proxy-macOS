import os,tempfile,unittest
from unittest.mock import Mock,patch
from devproxy_pkg.launch_policy import clean_flags,route_profile,environment
from devproxy_pkg.core.profile import ProxyProfile
from devproxy_pkg import macos_updates,preparation_state
from devproxy_pkg.core.recovery import StateManager
from devproxy_pkg.portable_runtime import load_profile

class LaunchPolicyTests(unittest.TestCase):
    def test_proxy_only_gemini_does_not_change_saved_profile(self):
        profile=ProxyProfile.parse('http://proxy.example:8080');profile.smart_dns=True
        effective=route_profile('gemini',profile)
        self.assertFalse(effective.smart_dns);self.assertTrue(profile.smart_dns);self.assertEqual(profile.host,effective.host)
        self.assertIs(profile,route_profile('codex',profile))
    def test_routing_flags_removed_and_unrelated_arguments_preserved(self):
        flags=['--folder','a b','--proxy-server','http://old:1','--proxy-pac-url=x','--no-proxy-server','--proxy-auto-detect','--proxy-bypass-list','*','--verbose']
        self.assertEqual(['--folder','a b','--verbose'],clean_flags(flags))
    def test_inherited_qt_routing_replaced(self):
        adapter=Mock();adapter.get_launch_environment.return_value={}
        with patch.dict(os.environ,QTWEBENGINE_CHROMIUM_FLAGS='--no-proxy-server --user-agent="some text"'):
            value=environment(adapter,'http://127.0.0.1:1234','fixture')['QTWEBENGINE_CHROMIUM_FLAGS']
        self.assertNotIn('--no-proxy-server',value);self.assertIn('--proxy-server=http://127.0.0.1:1234',value);self.assertIn('some text',value)
    def test_unreadable_profile_never_becomes_direct(self):
        with patch.object(StateManager,'get_profile',side_effect=OSError('fixture corrupt config')):
            with self.assertRaises(OSError):load_profile('fixture')
    def test_updater_refuses_root_before_network_or_mutation(self):
        with patch.object(macos_updates.os,'geteuid',return_value=0),patch.object(macos_updates,'root') as root:
            with self.assertRaisesRegex(ValueError,'root'):macos_updates.install('v0.4.1-mac.27-beta')
            root.assert_not_called()
    def test_damaged_launcher_is_recoverable_not_ready(self):
        with patch.object(preparation_state,'PortableShortcuts') as shortcuts:
            shortcuts.return_value.status.return_value={'enabled':False,'changed':['fixture']}
            result=preparation_state.inspect('codex')
        self.assertFalse(result['prepared']);self.assertTrue(result['recoverable'])
