import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg import ide_repair as repair
from devproxy_pkg.core.recovery import StateManager


class RepairTests(unittest.TestCase):
    def fixture(self,temp):
        root=Path(temp);original=root/'Original';original.write_bytes(b'original')
        bundle=repair.managed_root()/'old'/'IDE.app';bundle.mkdir(parents=True)
        old={'original':str(original),'bundle':str(bundle),'executable':str(bundle/'missing'),'backends':{'broken':'bad'}}
        StateManager.save_state({'prepared_macos':{'antigravity-ide':old},'profiles':{'kept':{'value':'fixture'}}})
        return old

    def test_corrupted_copy_is_rebuilt_and_only_old_copy_removed(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp+'/state'}):
            old=self.fixture(temp)
            def prepare():
                self.assertIsNone(repair.record('antigravity-ide'))
                bundle=repair.managed_root()/'new'/'IDE.app';bundle.mkdir(parents=True)
                state=StateManager.load_state();state['prepared_macos']['antigravity-ide']={**old,'bundle':str(bundle),'executable':str(bundle/'Electron')};StateManager.save_state(state)
            with patch.object(repair,'request',return_value=None),patch.object(repair,'require_stopped'),patch.object(repair,'checked_executable'),patch.object(repair,'codesign') as sign,patch('devproxy_pkg.ide_preparation.prepare',side_effect=prepare):
                repair.repair('antigravity-ide');sign.assert_called_once()
            self.assertFalse(Path(old['bundle']).exists());self.assertEqual(b'original',Path(old['original']).read_bytes());self.assertIn('kept',StateManager.load_state()['profiles'])

    def test_failed_repair_retains_old_state_and_copy(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp+'/state'}):
            old=self.fixture(temp)
            with patch.object(repair,'request',return_value=None),patch.object(repair,'require_stopped'),patch('devproxy_pkg.ide_preparation.prepare',side_effect=ValueError('unsupported fixture')):
                with self.assertRaises(ValueError):repair.repair('antigravity-ide')
            self.assertEqual(old,repair.record('antigravity-ide'));self.assertTrue(Path(old['bundle']).exists())

    def test_foreign_path_and_active_session_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp+'/state'}):
            with self.assertRaises(ValueError):repair.owned_directory({'bundle':temp+'/foreign/IDE.app'})
            with patch.object(repair,'request',return_value={'running':True}):
                with self.assertRaises(RuntimeError):repair.repair('antigravity-ide')
