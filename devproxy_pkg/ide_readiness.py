import http.client,json,platform,ssl
from .portable_runtime import load_profile
from .core.tunnel import LocalTunnel


def check_manifest(profile):
    hostname='antigravity-cli-auto-updater-974169037036.us-central1.run.app'
    architecture='arm64' if platform.machine()=='arm64' else 'amd64';path='/manifests/darwin_'+architecture+'.json'
    tunnel=LocalTunnel(load_profile(profile));connection=None
    try:
        port=tunnel.start();connection=http.client.HTTPSConnection('127.0.0.1',port,timeout=12,context=ssl.create_default_context());connection.set_tunnel(hostname,443)
        connection.request('GET',path,headers={'Host':hostname});reply=connection.getresponse();body=reply.read(262145)
        if reply.status!=200:raise RuntimeError('Сервер манифеста IDE вернул HTTP '+str(reply.status)+'. Профиль: '+profile+'. Адрес: https://'+hostname+path)
        if len(body)>262144 or not isinstance(json.loads(body),dict):raise ValueError('Некорректный release manifest IDE.')
        return 'Манифест IDE доступен через профиль «'+profile+'»: HTTP 200, '+architecture+'.'
    finally:
        if connection:connection.close()
        tunnel.stop()
