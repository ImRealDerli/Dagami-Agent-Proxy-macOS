import tempfile,os,unittest,json
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg import journal
from devproxy_pkg.system_dns import MacBackend

class JournalTests(unittest.TestCase):
    def test_no_credentials_or_oauth_url_in_journal(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}):
            journal.append('saveProxy',True,'https://user:private-password@proxy.example:443')
            journal.append('loginURL',True,'https://accounts.google.com/oauth?secret=fixture')
            journal.append('check',False,'https://user:private-password@proxy.example:443 Bearer abc123')
            text=journal.read()
            self.assertNotIn('private-password',text);self.assertNotIn('abc123',text);self.assertNotIn('secret=fixture',text)
            self.assertIn('check',text)
    def test_rotation_keeps_log_bounded(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}):
            path=journal.location();path.write_text('x'*(2*1024*1024+1));journal.append('check',True,'ok')
            self.assertTrue(path.with_suffix('.previous').exists());self.assertLess(path.stat().st_size,1000)

class SplitDnsTests(unittest.TestCase):
    def test_only_matching_global_dns_is_returned_to_auto(self):
        def execute(args):
            if '-listallnetworkservices' in args:return 'Services\nEthernet\nWi-Fi\n'
            if '-getdnsservers' in args:return '89.22.224.205' if args[-1]=='Ethernet' else '10.0.0.53'
            raise AssertionError(args)
        with tempfile.TemporaryDirectory() as temp:
            backend=MacBackend(execute,Path(temp).resolve()/'resolver')
            request={'mode':'domains','server':'89.22.224.205','preset':'Development','restore_global':True,'replace':False}
            changes=backend.plan(request);net=[v for v in changes if v['kind']=='dns']
            self.assertEqual([{'kind':'dns','id':'Ethernet','before':['89.22.224.205'],'after':[]}],net)
            self.assertTrue(any(v['id'].endswith('/deepseek.com') for v in changes))
            self.assertFalse(any(v['id'].endswith('/example.com') for v in changes))
            self.assertFalse(any(v['id'].endswith('/challenges.cloudflare.com') for v in changes))
            self.assertFalse(any(v['id'].endswith('/accounts.google.com') for v in changes))
    def test_domains_mode_does_not_touch_network_without_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            backend=MacBackend(lambda args:(_ for _ in ()).throw(AssertionError('unexpected network read')),Path(temp).resolve())
            changes=backend.plan({'mode':'domains','server':'89.22.224.205'})
            self.assertTrue(all(v['kind']=='file' for v in changes))
