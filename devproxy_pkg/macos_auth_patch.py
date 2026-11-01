from pathlib import Path
import hashlib,json,plistlib,struct

MARKER=b'dagami-auth-route-v1'

ENV_NEEDLE=b"const env = { ...process.env, ...(0, shell_env_1.shellEnvSync)() };"
AUTH_NEEDLE=b"if (authMatch) {"


def patch_language_server_js(content):
    if content.count(ENV_NEEDLE)!=1 or content.count(AUTH_NEEDLE)!=1 or b'dagami-backend-auth-v2' in content:raise ValueError('Неизвестный механизм запуска backend Antigravity. Файл не изменён.')
    env=ENV_NEEDLE+b"\nif (process.env.DAGAMI_AUTH_TOKEN && process.env.DAGAMI_AUTH_PORT) {\n env.ANTIGRAVITY_VSCODE_HOST = '1';\n for (const key of ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy','NO_PROXY','no_proxy','AG_LS_PROXY','AGY_PROXY_URL','agy_proxy_url','DAGAMI_AUTH_PORT','DAGAMI_AUTH_TOKEN']) {if (process.env[key] !== undefined) env[key] = process.env[key];}\n}\nvoid 'dagami-backend-auth-v2';"
    auth=b"if (authMatch && process.env.DAGAMI_AUTH_TOKEN && !extractOpenUrl(line)) { void electron_1.shell.openExternal(authMatch[0]); }\n"+AUTH_NEEDLE
    return content.replace(ENV_NEEDLE,env).replace(AUTH_NEEDLE,auth)


def rewrite_archive(data,hook):
    if len(data)<16:raise ValueError('Некорректный ASAR.')
    size,header_size,payload_size,string_size=struct.unpack_from('<4I',data)
    if size!=4 or header_size!=payload_size+4 or string_size>payload_size-4 or 8+header_size>len(data):raise ValueError('Неизвестный формат ASAR.')
    header=json.loads(data[16:16+string_size]);base=8+header_size;entries=[]
    def visit(node,prefix=''):
        for name,item in node.get('files',{}).items():
            full=prefix+name
            if 'files' in item:visit(item,full+'/')
            elif 'offset' in item:
                start=int(item['offset']);length=int(item['size'])
                if start<0 or length<0 or base+start+length>len(data):raise ValueError('Обрезанный ASAR.')
                entries.append((start,full,item,data[base+start:base+start+length]))
    visit(header)
    files={name:content for _,name,_,content in entries}
    package=json.loads(files.get('package.json',b'{}'));main=files.get('dist/main.js',b'')
    if package.get('name')!='antigravity' or package.get('main')!='dist/main.js' or b'require("electron")' not in main or b'require("./languageServer")' not in main or not main.startswith(b'"use strict";') or MARKER in main:
        raise ValueError('Неизвестная структура входа Antigravity. Оригинал не изменён.')
    backend=patch_language_server_js(files.get('dist/languageServer.js',b''))
    output=bytearray();end=0
    for start,name,item,content in sorted(entries,key=lambda v:v[0]):
        if start<end:raise ValueError('Перекрывающиеся записи ASAR.')
        end=start+len(content)
        if name=='dist/main.js':
            content=b'"use strict";\n'+hook+b'\n'+content[len(b'"use strict";'):]
        if name=='dist/languageServer.js':content=backend
        if name in ('dist/main.js','dist/languageServer.js'):
            integrity=item.get('integrity',{});block=int(integrity.get('blockSize',4194304))
            if not 1<=block<=16777216:raise ValueError('Неизвестный блок ASAR.')
            item['integrity']={'algorithm':'SHA256','hash':hashlib.sha256(content).hexdigest(),'blockSize':block,'blocks':[hashlib.sha256(content[i:i+block]).hexdigest() for i in range(0,len(content),block)]}
        item['offset']=str(len(output));item['size']=len(content);output.extend(content)
    encoded=json.dumps(header,ensure_ascii=False,separators=(',',':')).encode()
    payload=struct.pack('<I',len(encoded))+encoded+b'\0'*((-len(encoded))%4)
    pickle=struct.pack('<I',len(payload))+payload
    return struct.pack('<II',4,len(pickle))+pickle+output,hashlib.sha256(encoded).hexdigest()


def patch_bundle(bundle):
    bundle=Path(bundle);archive=bundle/'Contents/Resources/app.asar'
    if not archive.is_file():return []
    info_path=bundle/'Contents/Info.plist';info=plistlib.loads(info_path.read_bytes())
    integrity=info.get('ElectronAsarIntegrity',{}).get('Resources/app.asar',{})
    if integrity.get('algorithm')!='SHA256':raise ValueError('Неизвестная проверка целостности ASAR.')
    data=archive.read_bytes();size=struct.unpack_from('<I',data,12)[0]
    if hashlib.sha256(data[16:16+size]).hexdigest()!=integrity.get('hash'):raise ValueError('Исходный ASAR повреждён. Подготовка отменена.')
    hook=(Path(__file__).resolve().parent.parent/'native/macos/antigravity_auth_hook.js').read_bytes()
    changed,header_hash=rewrite_archive(data,hook)
    archive.write_bytes(changed);integrity['hash']=header_hash
    info_path.write_bytes(plistlib.dumps(info))
    return [archive.relative_to(bundle).as_posix(),info_path.relative_to(bundle).as_posix()]
