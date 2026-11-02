import hashlib,http.client,json,os,re,ssl,subprocess,time
from .desktop_processes import inventory
from .terminal_sessions import process_arguments
from .session_telemetry import number,text,timestamp
from .journal import register_secret

METHODS=('RetrieveUserQuotaSummary','GetUserStatus')

def decimal(value,low=0,high=1):
    if isinstance(value,str):
        try:value=float(value)
        except ValueError:return None
    return number(value,low,high)

def reset(value):
    if type(value) in (int,float) and value>4102444800:value=value/1000
    return timestamp(value)

def normalize(payload,method):
    rows=[]
    if not isinstance(payload,dict):raise ValueError('Неизвестный формат квот Antigravity.')
    if method=='RetrieveUserQuotaSummary':
        response=payload.get('response',{})
        if not isinstance(response,dict):response={}
        groups=response.get('groups',[])
        if not isinstance(groups,list):groups=[]
        for index,group in enumerate(groups[:16]):
            if not isinstance(group,dict):continue
            buckets=group.get('buckets',[])
            if not isinstance(buckets,list):continue
            for count,bucket in enumerate(buckets[:8]):
                if not isinstance(bucket,dict):continue
                fraction=decimal(bucket.get('remainingFraction'))
                if fraction is None:continue
                rows.append({'id':str(index)+'_'+str(count),'label':text(group.get('displayName','Модели'))+' · '+text(bucket.get('window','Окно сервиса')),'usedPercent':round(100*(1-fraction),2),'resetAt':reset(bucket.get('resetTime')),'disabled':False})
    else:
        status=payload.get('userStatus',{})
        if not isinstance(status,dict):status={}
        cascade=status.get('cascadeModelConfigData',{})
        if not isinstance(cascade,dict):cascade={}
        models=cascade.get('clientModelConfigs',[])
        if not isinstance(models,list):models=[]
        for index,model in enumerate(models[:32]):
            if not isinstance(model,dict):continue
            quota=model.get('quotaInfo')
            if not isinstance(quota,dict):continue
            fraction=decimal(quota.get('remainingFraction'))
            if fraction is not None:rows.append({'id':str(index),'label':text(model.get('label','Модель')),'usedPercent':round(100*(1-fraction),2),'resetAt':reset(quota.get('resetTime')),'disabled':False})
    return {'updatedAt':time.time(),'source':'Локальный сервер Antigravity · внутренний интерфейс','quotas':rows,'note':'Данные выбранной запущенной Antigravity. Интерфейс не является публичным API Google и может измениться.'}

def candidates(session):
    data=inventory();owned={pid for pid in session.get('pids',[]) if type(pid) is int}
    changed=True
    while changed:
        children={pid for pid,item in data.items() if item['parent'] in owned and item['uid']==os.getuid()};new=children-owned;owned|=new;changed=bool(new)
    servers=[]
    for pid in owned:
        item=data.get(pid)
        if not item or item['uid']!=os.getuid() or not item['name'].startswith('language_server'):continue
        args=process_arguments(pid);token=''
        for index,value in enumerate(args):
            if value.startswith('--csrf_token='):token=value.split('=',1)[1]
            elif value=='--csrf_token' and index+1<len(args):token=args[index+1]
        if not re.fullmatch('[A-Za-z0-9_-]{16,256}',token):continue
        result=subprocess.run(['/usr/sbin/lsof','-nP','-a','-p',str(pid),'-iTCP','-sTCP:LISTEN','-Fpn'],capture_output=True,text=True,timeout=2)
        ports=[]
        for line in result.stdout.splitlines():
            match=re.fullmatch(r'n(?:127\.0\.0\.1|\[::1\]):([0-9]+)',line)
            if match and 1<=int(match[1])<=65535:ports.append(int(match[1]))
        register_secret(token)
        for port in sorted(set(ports))[:3]:servers.append((pid,port,token,item['path']))
    return servers[:6]

def post(endpoint,method):
    pid,port,token,path=endpoint
    current=inventory().get(pid)
    if not current or current['path']!=path or current['uid']!=os.getuid():raise RuntimeError('Локальный сервер Antigravity изменился. Обновите сессию.')
    probe_context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);probe_context.check_hostname=False;probe_context.verify_mode=ssl.CERT_NONE
    probe=http.client.HTTPSConnection('127.0.0.1',port,timeout=1.5,context=probe_context)
    try:
        probe.connect();certificate=probe.sock.getpeercert(binary_form=True)
    finally:probe.close()
    context=ssl.create_default_context();context.check_hostname=False;context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(certificate))
    context.verify_flags|=getattr(ssl,'VERIFY_X509_PARTIAL_CHAIN',0)
    client=http.client.HTTPSConnection('127.0.0.1',port,timeout=2,context=context)
    try:
        client.connect()
        if hashlib.sha256(client.sock.getpeercert(binary_form=True)).digest()!=hashlib.sha256(certificate).digest():raise RuntimeError('Изменился сертификат локального сервера.')
        client.request('POST','/exa.language_server_pb.LanguageServerService/'+method,json.dumps({'metadata':{'ideName':'antigravity'}}),{'Content-Type':'application/json','X-Codeium-Csrf-Token':token,'Connect-Protocol-Version':'1'})
        reply=client.getresponse();raw=reply.read(1048577)
        if len(raw)>1048576:raise RuntimeError('Слишком большой ответ локального сервера.')
        if reply.status!=200:raise RuntimeError('Локальный сервер отклонил чтение квот (HTTP '+str(reply.status)+').')
        value=json.loads(raw)
        if not isinstance(value,dict):raise RuntimeError('Неизвестный формат квот Antigravity.')
        return normalize(value,method)
    finally:client.close()

def for_session(identifier):
    from .macos_activity import sessions
    row=next((row for row in sessions() if row['id']==identifier),None)
    if row is None or (row.get('app') or row['id']) not in ('antigravity','antigravity-ide'):raise ValueError('Выберите запущенную Antigravity App или IDE.')
    endpoints=candidates(row)
    if not endpoints:raise RuntimeError('Не найден локальный сервер выбранной сессии. Полностью перезапустите Antigravity через Dagami.')
    failures=[];deadline=time.monotonic()+12
    for endpoint in endpoints:
        for method in METHODS:
            if time.monotonic()>deadline:break
            try:
                result=post(endpoint,method)
                if result['quotas']:return result
            except (OSError,ValueError,RuntimeError,http.client.HTTPException):failures.append(True)
    raise RuntimeError('Локальный сервер не предоставил квоты. Проверьте вход и панель Usage в самой Antigravity. Google-токены не извлекаются.')
