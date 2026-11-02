import http.server,json,os,ssl,subprocess,sys,tempfile,threading,time,tomllib,unittest
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg import session_telemetry as telemetry,codex_limits,antigravity_limits as ag,desktop_monitoring as desktop
from devproxy_pkg.core.recovery import StateManager

class InsightsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
        env=patch.dict(os.environ,DEVPROXY_HOME=self.temp.name);env.start();self.addCleanup(env.stop)
    def test_status_allowlist_discards_conversation_account_and_secrets(self):
        payload={'prompt':'private prompt','email':'private@example.com','transcript_path':'/private/chat','access_token':'private-secret','model':{'display_name':'Gemini'},'agent_state':'tool_use','quota':{'weekly':{'remaining_fraction':.75,'reset_time':'2030-01-02T03:04:00Z'}}}
        path=telemetry.root()/('a'*32+'.json');telemetry.receive('agy','status',payload,path)
        text=path.read_text();self.assertNotIn('private',text)
        data=json.loads(text);self.assertEqual('tool_use',data['state']);self.assertEqual(25,data['quotas'][0]['usedPercent'])
        self.assertEqual(0o600,path.stat().st_mode&0o777)
    def test_unknown_numbers_never_become_zero_limits(self):
        data=telemetry.clean_status('claude',{'rate_limits':{'five_hour':{'used_percentage':None},'seven_day':{'used_percentage':False}}})
        self.assertEqual([],data['quotas'])
        self.assertIsNone(telemetry.number(float('nan')))
    def test_monitoring_off_prevents_writes(self):
        StateManager.save_state({'session_monitoring':False})
        path=telemetry.root()/('b'*32+'.json');telemetry.receive('agy','status',{'agent_state':'working'},path)
        self.assertFalse(path.exists())
    def test_path_traversal_and_symlinks_rejected(self):
        with self.assertRaises(ValueError):telemetry.write(self.base/'outside.json',{})
        path=telemetry.root()/('c'*32+'.json');path.symlink_to(self.base/'outside.json')
        with self.assertRaises(ValueError):telemetry.write(path,{})
    def test_codex_runtime_hooks_are_stable_and_do_not_bypass_trust(self):
        with patch.object(telemetry.subprocess,'run',return_value=type('Help',(),{'stdout':'--config --dangerously-bypass-hook-trust'})()):
            one=telemetry.Telemetry('codex','/fixture/codex');two=telemetry.Telemetry('codex','/fixture/codex')
        try:
            self.assertEqual(one.flags,two.flags);self.assertNotIn('--dangerously-bypass-hook-trust',one.flags)
            for item in one.flags[1::2]:self.assertIn('hooks',tomllib.loads(item))
        finally:one.close();two.close()
    def test_agy_help_on_stderr_enables_status_and_quota_collection(self):
        result=subprocess.CompletedProcess([],0,stdout='',stderr='Usage of agy: --settings')
        with patch.object(telemetry.subprocess,'run',return_value=result):item=telemetry.Telemetry('agy','/fixture/agy')
        try:
            self.assertIsNotNone(item.path)
            settings=json.loads(item.flags[1]);self.assertTrue(settings['statusLine']['stack_with_default'])
            telemetry.receive('agy','status',{'agent_state':'working','quota':{'weekly':{'remaining_fraction':.75}}},item.path)
            self.assertEqual('working',item.snapshot()['state']);self.assertEqual(25,item.snapshot()['quotas'][0]['usedPercent'])
            telemetry.receive('agy','status',{'agent_state':'idle','quota':{'weekly':{'remaining_fraction':.7}}},item.path)
            self.assertEqual('idle',item.snapshot()['state']);self.assertEqual(30,item.snapshot()['quotas'][0]['usedPercent'])
        finally:item.close()

    def test_claude_uses_additive_plugin_not_settings_hook_override(self):
        with patch.object(telemetry.subprocess,'run',return_value=type('Help',(),{'stdout':'--settings --plugin-dir'})()):item=telemetry.Telemetry('claude','/fixture/claude')
        try:
            settings=json.loads(item.flags[1]);self.assertNotIn('hooks',settings);self.assertIn('--plugin-dir',item.flags)
            self.assertTrue((item.plugin/'hooks/hooks.json').exists())
        finally:item.close()
    def test_hook_events_preserve_quota_and_stale_state_is_not_claimed_current(self):
        item=telemetry.Telemetry('antigravity','/fixture/app')
        try:
            telemetry.receive('agy','status',{'agent_state':'working','quota':{'weekly':{'remaining_fraction':.8}}},item.path)
            telemetry.receive('antigravity-desktop','Stop',{'prompt':'do not save'},item.path)
            self.assertEqual('idle',item.snapshot()['state']);self.assertEqual(20,item.snapshot()['quotas'][0]['usedPercent'])
            telemetry.write(item.path,{'activityAt':time.time()-400,'state':'working'})
            self.assertEqual('unknown',item.snapshot()['state'])
        finally:item.close()
    def test_codex_only_read_rpc_methods_sent_and_no_auth_file_read(self):
        script=self.base/'server.py';script.write_text('''import sys,json
for line in sys.stdin:
 data=json.loads(line)
 if data['method']=='initialize':print(json.dumps({'id':data['id'],'result':{}}),flush=True)
 elif data['method']=='initialized':pass
 elif data['method']=='account/rateLimits/read':print(json.dumps({'id':data['id'],'result':{'rateLimits':{'primary':{'usedPercent':35,'windowDurationMins':300,'resetsAt':2000000000}}}}),flush=True)
 else:raise RuntimeError('Unexpected operation')
''')
        data=codex_limits.query([sys.executable,str(script)],dict(os.environ),timeout=3)
        self.assertEqual(35,data['quotas'][0]['usedPercent']);self.assertIn('read',data['source'])
    def test_codex_missing_and_invalid_quota_windows_not_invented(self):
        self.assertEqual([],codex_limits.normalize({'rateLimits':None})['quotas'])
        self.assertEqual([],codex_limits.normalize({'rateLimits':{'primary':{'usedPercent':-1}}})['quotas'])
    def test_antigravity_summary_and_fallback_exclude_account_identity(self):
        data=ag.normalize({'response':{'groups':[{'displayName':'Gemini','buckets':[{'window':'weekly','remainingFraction':'0.8','resetTime':'2030-01-01T00:00:00Z'}]}]},'email':'not-for-export'},'RetrieveUserQuotaSummary')
        self.assertEqual(20,data['quotas'][0]['usedPercent']);self.assertNotIn('not-for-export',json.dumps(data))
        data=ag.normalize({'userStatus':{'email':'hidden','cascadeModelConfigData':{'clientModelConfigs':[{'label':'Gemini','quotaInfo':{'remainingFraction':.25,'resetTime':2000000000000}}]}}},'GetUserStatus')
        self.assertEqual(75,data['quotas'][0]['usedPercent']);self.assertEqual(2000000000,data['quotas'][0]['resetAt']);self.assertNotIn('hidden',json.dumps(data))
    def test_desktop_hooks_merge_restore_and_do_not_change_permissions(self):
        config=self.base/'config/hooks.json';record=self.base/'record.json';config.parent.mkdir();original={'user-rule':{'Stop':[{'command':'user-original'}]}};config.write_text(json.dumps(original))
        with patch.object(desktop,'paths',return_value=(config,record)):
            desktop.configure(True);self.assertTrue(desktop.installed())
            value=json.loads(config.read_text());self.assertEqual(original['user-rule'],value['user-rule'])
            managed=value[desktop.GROUP]
            self.assertNotIn('decision',json.dumps(managed));self.assertNotIn('force_continue',json.dumps(managed))
            desktop.configure(False);self.assertEqual(original,json.loads(config.read_text()))
    def test_manual_desktop_hook_edits_are_preserved(self):
        config=self.base/'hooks.json';record=self.base/'record.json'
        with patch.object(desktop,'paths',return_value=(config,record)):
            desktop.configure(True);config.write_text(json.dumps({desktop.GROUP:{'edited':True}}))
            with self.assertRaises(RuntimeError):desktop.configure(False)
            self.assertTrue(json.loads(config.read_text())[desktop.GROUP]['edited'])
    def test_loopback_antigravity_tls_pins_leaf_before_sending_csrf(self):
        key=self.base/'key.pem';cert=self.base/'cert.pem'
        subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost'],check=True,capture_output=True)
        calls=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                calls.append((self.path,self.headers.get('X-Codeium-Csrf-Token')));self.rfile.read(int(self.headers['Content-Length']))
                data=json.dumps({'response':{'groups':[{'displayName':'Gemini','buckets':[{'window':'weekly','remainingFraction':.5}]}]}}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key);server.socket=context.wrap_socket(server.socket,server_side=True)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            pid=os.getpid();info={pid:{'path':'/fixture/language_server','uid':os.getuid()}}
            with patch.object(ag,'inventory',return_value=info):data=ag.post((pid,server.server_port,'fixture-local-csrf-token','/fixture/language_server'),'RetrieveUserQuotaSummary')
            self.assertEqual(50,data['quotas'][0]['usedPercent']);self.assertEqual(1,len(calls));self.assertEqual('fixture-local-csrf-token',calls[0][1])
        finally:server.shutdown();server.server_close();worker.join(timeout=2)
