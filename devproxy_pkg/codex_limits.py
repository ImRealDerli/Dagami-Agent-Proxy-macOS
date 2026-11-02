import json,os,selectors,signal,subprocess,time
from .session_telemetry import number,timestamp,text


def normalize(result):
    if not isinstance(result,dict):raise ValueError('Неизвестный формат лимитов Codex.')
    buckets=result.get('rateLimitsByLimitId')
    if not isinstance(buckets,dict):buckets={'codex':result.get('rateLimits',{})}
    rows=[]
    for bucket,value in list(buckets.items())[:16]:
        if not isinstance(value,dict):continue
        for key in ('primary','secondary'):
            window=value.get(key)
            if not isinstance(window,dict):continue
            used=number(window.get('usedPercent'))
            if used is None:continue
            minutes=number(window.get('windowDurationMins'),1,525600)
            label=text(value.get('limitName') or bucket)
            if minutes:label+=' · '+(str(round(minutes/60,1))+' ч' if minutes<1440 else str(round(minutes/1440,1))+' дн')
            rows.append({'id':text(bucket)+'_'+key,'label':label,'usedPercent':used,'resetAt':timestamp(window.get('resetsAt')),'disabled':False})
    return {'updatedAt':time.time(),'source':'Codex app-server · account/rateLimits/read','quotas':rows,'note':'Лимиты аккаунта Codex. Общие для его сессий.' if rows else 'Клиент не предоставил лимиты подписки. Для API-ключа они могут быть недоступны.'}


def query(command,env,timeout=15):
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env,start_new_session=True)
    selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ);buffer=bytearray();total=0;deadline=time.monotonic()+timeout
    def send(value):process.stdin.write(json.dumps(value).encode()+b'\n');process.stdin.flush()
    def response(identifier):
        nonlocal buffer,total
        while time.monotonic()<deadline:
            while b'\n' in buffer:
                line,_,buffer=buffer.partition(b'\n')
                try:value=json.loads(line)
                except ValueError:continue
                if not isinstance(value,dict) or value.get('id')!=identifier:continue
                if 'error' in value:raise RuntimeError('Codex не предоставил лимиты. Проверьте штатный вход в клиенте.')
                return value.get('result',{})
            if not selector.select(min(.2,max(0,deadline-time.monotonic()))):continue
            data=os.read(process.stdout.fileno(),65536)
            if not data:raise RuntimeError('Codex app-server завершился до получения лимитов.')
            total+=len(data)
            if total>1048576:raise RuntimeError('Ответ клиента слишком большой.')
            buffer.extend(data)
        raise TimeoutError('Клиент не ответил за 15 секунд. Попробуйте позже.')
    try:
        send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'dagami_session_monitor','title':'Dagami session monitor','version':'0.4.0-mac.26-test'}}})
        response(1);send({'method':'initialized','params':{}});send({'id':2,'method':'account/rateLimits/read'})
        return normalize(response(2))
    finally:
        selector.close()
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=2)
        process.stdin.close();process.stdout.close()


def for_session(identifier):
    from .macos_activity import sessions
    from .portable_runtime import app_adapter,executable,load_profile
    from .core.process_env import independent_environment
    from .core.tunnel import LocalTunnel
    row=next((row for row in sessions() if row['id']==identifier),None)
    if row is None:raise ValueError('Сессия уже завершилась. Обновите список.')
    app=row.get('app') or row['id']
    if app not in ('codex','codex-gui'):raise ValueError('Для этого клиента используйте официальную панель лимитов.')
    tunnel=LocalTunnel(load_profile(row['profile']))
    try:
        local='http://127.0.0.1:'+str(tunnel.start())
        env=independent_environment();env.update({name:local for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy')});env.update(NO_PROXY='localhost,127.0.0.1,::1',no_proxy='localhost,127.0.0.1,::1')
        return query([executable(app_adapter('codex')),'app-server','--listen','stdio://'],env)
    finally:tunnel.stop()
