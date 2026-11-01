import unittest
from unittest.mock import patch,MagicMock
from devproxy_pkg import codex_preparation

class CodexPreparationTests(unittest.TestCase):
    def test_preparation_uses_managed_launcher_and_never_patches_codex_binary(self):
        with patch.object(codex_preparation,'executable',return_value='/fixture/codex'),patch.object(codex_preparation,'require_stopped'),patch.object(codex_preparation,'request',return_value=None),patch.object(codex_preparation,'PortableShortcuts') as shortcuts:
            shortcuts.return_value.status.return_value={'enabled':False,'changed':[]}
            codex_preparation.prepare('codex','fixture')
            shortcuts.return_value.enable.assert_called_once_with('codex','fixture')
    def test_restore_only_removes_managed_launch_preparation(self):
        with patch.object(codex_preparation,'request',return_value=None),patch.object(codex_preparation,'PortableShortcuts') as shortcuts:
            codex_preparation.restore('codex');shortcuts.return_value.restore.assert_called_once_with('codex')
    def test_active_codex_session_is_not_closed_by_preparation(self):
        with patch.object(codex_preparation,'executable',return_value='/fixture/codex'),patch.object(codex_preparation,'require_stopped'),patch.object(codex_preparation,'request',return_value={'running':True}),patch.object(codex_preparation,'PortableShortcuts') as shortcuts:
            with self.assertRaises(ValueError):codex_preparation.prepare('codex','fixture')
            shortcuts.assert_not_called()
