import json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from devproxy_pkg import journal,macos_activity as activity

class ActivityTests(unittest.TestCase):
    def test_history_explains_errors_and_preserves_details(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,DEVPROXY_HOME=root):
            journal.append('prepare',False,'Traceback\ncodesign exited with status 1\nstderr: invalid signature',detail=True)
            item=activity.entries()[0]
            self.assertEqual(item['title'],'Применение патча')
            self.assertIn('подписи',item['summary']);self.assertIn('stderr:',item['detail'])
    def test_partial_check_is_error_even_for_old_success_records(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,DEVPROXY_HOME=root):
            journal.append('check',True,'✓ Google: TLS проверен\n✕ GitHub: HTTP 503')
            item=activity.entries()[0]
            self.assertFalse(item['success']);self.assertIn('1 из 2',item['summary'])
    def test_historical_credentials_are_redacted_again(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,DEVPROXY_HOME=root):
            journal.location().write_text(json.dumps({'time':'fixture','action':'check','success':False,'message':'https://user:fixture-password@proxy.example/?token=value'}))
            self.assertNotIn('fixture-password',json.dumps(activity.entries()))
            self.assertNotIn('token=value',json.dumps(activity.entries()))
    def test_read_polling_does_not_fill_journal(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,DEVPROXY_HOME=root):
            journal.append('sessions',True,'fixture');journal.append('journalEntries',True,'fixture')
            self.assertEqual(activity.entries(),[])
    def test_sessions_only_expose_selected_status_fields(self):
        adapter=SimpleNamespace(app_id='fixture',display_name='Fixture')
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'fixture.json').write_text('{}')
            with patch.object(activity,'runtime_dir',return_value=Path(root)),patch.object(activity,'list_adapters',return_value=[adapter]),patch.object(activity,'request',return_value={'profile':'DNS','running':True,'token':'private-token','pid':23,'application_pids':[24],'bridge':'http://127.0.0.1:4444'}) as req:
                result=activity.sessions()
                self.assertEqual(result[0]['pids'],[24]);self.assertNotIn('private-token',json.dumps(result))
                req.assert_called_once_with('fixture',_timeout=1.5)
    def test_busy_controller_is_not_reported_as_stopping(self):
        adapter=SimpleNamespace(app_id='fixture',display_name='Fixture')
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'fixture.json').write_text('{}')
            with patch.object(activity,'runtime_dir',return_value=Path(root)),patch.object(activity,'list_adapters',return_value=[adapter]),patch.object(activity,'request',return_value={'profile':'DNS','stopping':True,'running':False}):
                item=activity.sessions()[0]
                self.assertFalse(item['stopping']);self.assertIn('не ответил',item['error'])
    def test_dead_and_symlink_descriptors_not_shown(self):
        adapters=[SimpleNamespace(app_id=n,display_name=n) for n in ('dead','linked')]
        with tempfile.TemporaryDirectory() as root:
            path=Path(root);(path/'dead.json').write_text('{}');(path/'linked.json').symlink_to(path/'dead.json')
            with patch.object(activity,'runtime_dir',return_value=path),patch.object(activity,'list_adapters',return_value=adapters),patch.object(activity,'request',return_value=None) as req:
                self.assertEqual(activity.sessions(),[]);self.assertEqual(req.call_count,1)

if __name__=='__main__':unittest.main()
