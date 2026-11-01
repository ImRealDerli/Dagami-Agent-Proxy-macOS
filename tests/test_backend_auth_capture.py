import json,shutil,subprocess,unittest
from devproxy_pkg.macos_auth_patch import patch_language_server_js

class BackendCaptureTests(unittest.TestCase):
    def test_unknown_backend_host_logic_is_not_modified(self):
        with self.assertRaisesRegex(ValueError,'Неизвестный'):patch_language_server_js(b'unknown backend')

    @unittest.skipUnless(shutil.which('node'),'Node fixture')
    def test_backend_exports_url_and_restores_selected_route_after_shell_import(self):
        source=b'''const shell_env_1={shellEnvSync:()=>({HTTP_PROXY:'http://wrong-route:9',PATH:'shell-tools'})};
const env = { ...process.env, ...(0, shell_env_1.shellEnvSync)() };
const received=[];const electron_1={shell:{openExternal:url=>received.push(url)}};
function extractOpenUrl(line){return line.startsWith('ANTIGRAVITY_OPEN_URL: ')?line.slice(22):null;}
function route(line){const authMatch=line.match(/https:\/\/accounts.google.com\/o\/oauth2\/auth\\S+/);if (authMatch) {}
const openUrl=extractOpenUrl(line);if(openUrl)electron_1.shell.openExternal(openUrl);}
'''
        changed=patch_language_server_js(source).decode()
        script='''const vm=require('vm');const context={process:{env:{HTTP_PROXY:'http://127.0.0.1:33333',HTTPS_PROXY:'http://127.0.0.1:33333',DAGAMI_AUTH_TOKEN:'a'.repeat(64),DAGAMI_AUTH_PORT:'44444'}}};vm.createContext(context);vm.runInContext(process.argv[1]+`;const url='https://accounts.google.com/o/oauth2/auth?client_id=fixture&state=nonce&code_challenge=pkce&redirect_uri=http%3A%2F%2Flocalhost%3A1455';route(url);route('ANTIGRAVITY_OPEN_URL: '+url);`,context);console.log(vm.runInContext('JSON.stringify({env,received})',context));'''
        run=subprocess.run(['node','-e',script,changed],capture_output=True,text=True,check=True,timeout=10);data=json.loads(run.stdout)
        self.assertEqual('1',data['env']['ANTIGRAVITY_VSCODE_HOST']);self.assertEqual('http://127.0.0.1:33333',data['env']['HTTP_PROXY']);self.assertEqual('shell-tools',data['env']['PATH'])
        self.assertEqual(2,len(data['received']));self.assertEqual(data['received'][0],data['received'][1]);self.assertIn('code_challenge=pkce',data['received'][0])
