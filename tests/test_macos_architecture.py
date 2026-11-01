import os,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from devproxy_pkg.macos_architecture import executable_architectures,compatibility_error,host_architecture
from devproxy_pkg.adapters.chatgpt_web import ChatGPTWebAdapter
from devproxy_pkg.core.profile import ProxyProfile
from devproxy_pkg import desktop_processes


class ArchitectureTests(unittest.TestCase):
    def binary(self,root,data):
        path=Path(root)/'App';path.write_bytes(data);return path

    def test_arm_only_is_explained_on_intel_before_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.binary(temp,b'\xcf\xfa\xed\xfe'+struct.pack('<I',0x0100000c)+b'\0'*24)
            self.assertEqual({'arm64'},executable_architectures(path));self.assertIn('Intel',compatibility_error(path,'x86_64'));self.assertIsNone(compatibility_error(path,'arm64'))

    def test_fat_universal_allows_intel_and_arm(self):
        with tempfile.TemporaryDirectory() as temp:
            data=b'\xca\xfe\xba\xbe'+struct.pack('>I',2)+struct.pack('>IIIII',0x01000007,3,0,0,0)+struct.pack('>IIIII',0x0100000c,0,0,0,0)
            path=self.binary(temp,data);self.assertEqual({'x86_64','arm64'},executable_architectures(path))
            self.assertIsNone(compatibility_error(path,'arm64'));self.assertIsNone(compatibility_error(path,'x86_64'))

    def test_scripts_and_truncated_headers_are_not_misidentified(self):
        with tempfile.TemporaryDirectory() as temp:
            for data in (b'#!/bin/sh\nexit 0',b'\xca\xfe\xba\xbe'+struct.pack('>I',9999)):
                self.assertEqual(set(),executable_architectures(self.binary(temp,data)))

    def test_rosetta_uses_physical_arm_support(self):
        host_architecture.cache_clear()
        try:
            with patch('devproxy_pkg.macos_architecture.subprocess.run',return_value=Mock(returncode=0,stdout='1\n')):
                self.assertEqual('arm64',host_architecture())
        finally:host_architecture.cache_clear()

    def test_incompatible_launch_is_blocked_before_opening_session(self):
        from devproxy_pkg import portable_runtime
        with tempfile.TemporaryDirectory() as temp:
            path=self.binary(temp,b'\xcf\xfa\xed\xfe'+struct.pack('<I',0x0100000c))
            with patch.object(portable_runtime,'load_profile'),patch.object(portable_runtime,'executable',return_value=str(path)),patch('devproxy_pkg.macos_architecture.host_architecture',return_value='x86_64'),patch.object(portable_runtime,'request',return_value=None) as request:
                with self.assertRaisesRegex(RuntimeError,'Несовместимая архитектура'):portable_runtime.start_session('chatgpt','fixture')
                request.assert_called_once_with('chatgpt')

    def test_web_profile_is_separate_and_normal_browser_is_not_targeted(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}):
            adapter=ChatGPTWebAdapter();first=ProxyProfile.parse('direct://',name='one');second=ProxyProfile.parse('direct://',name='two')
            one=adapter.launch_flags(first);two=adapter.launch_flags(second)
            self.assertIn('--app=https://chatgpt.com/',one)
            self.assertNotEqual(next(v for v in one if v.startswith('--user-data-dir=')),next(v for v in two if v.startswith('--user-data-dir=')))
            item={'pid':99001,'parent':1,'uid':os.getuid(),'path':'/Applications/Brave Browser.app/Contents/MacOS/Brave Browser','name':'Brave Browser'}
            with patch('devproxy_pkg.portable_runtime.executable',return_value=item['path']),patch('devproxy_pkg.portable_runtime.request',return_value=None),patch.object(desktop_processes,'inventory',return_value={99001:item}):
                self.assertEqual([],desktop_processes.inspect('chatgpt-web')['processes'])
