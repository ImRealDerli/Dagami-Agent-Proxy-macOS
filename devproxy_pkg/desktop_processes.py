import os,signal,subprocess,time
from pathlib import Path
from .core.process_env import external_environment


def inventory():
    result=subprocess.run(['ps','-axo','pid=,ppid=,uid=,stat=,comm='],capture_output=True,text=True,check=True,timeout=10,env=external_environment())
    items={}
    for line in result.stdout.splitlines():
        fields=line.strip().split(None,4)
        if len(fields)!=5 or not all(v.isdigit() for v in fields[:3]) or fields[3].startswith('Z'):continue
        pid,parent,uid=map(int,fields[:3]);items[pid]={'pid':pid,'parent':parent,'uid':uid,'path':os.path.realpath(fields[4]),'name':Path(fields[4]).name}
    return items


def inspect(app):
    from .portable_runtime import app_adapter,executable,request
    from .macos_backend import record
    adapter=app_adapter(app)
    if adapter.is_cli:return {'cli':True,'processes':[]}
    candidates=[]
    try:candidates.append(Path(executable(adapter)).resolve())
    except RuntimeError:pass
    prepared=record(app) or {}
    if prepared.get('original'):candidates.append(Path(prepared['original']).resolve())
    if getattr(adapter,'isolated_browser',False) is True:candidates=[]
    bundles={next((p for p in path.parents if p.suffix=='.app'),None) for path in candidates};bundles.discard(None)
    shared={'python','python3','python3.12','node','sh','bash','zsh','electron'}
    candidates=[path for path in candidates if any(path.is_relative_to(root) for root in bundles) or path.name.lower() not in shared]
    data=inventory();matched=set()
    for pid,item in data.items():
        path=Path(item['path'])
        if path in candidates or any(path.is_relative_to(root) for root in bundles):matched.add(pid)
    status=request(app)
    if status and isinstance(status.get('pid'),int) and status['pid'] in data:
        pid=status['pid'];args=subprocess.run(['ps','-p',str(pid),'-o','args='],capture_output=True,text=True,timeout=5,check=True,env=external_environment()).stdout
        if 'devproxy_gui.py session '+app+' ' in args:matched.add(pid)
    changed=True
    while changed:
        children={pid for pid,item in data.items() if item['parent'] in matched};new=children-matched;matched|=children;changed=bool(new)
    processes=[data[pid] for pid in sorted(matched) if pid not in (os.getpid(),os.getppid())]
    return {'cli':False,'processes':processes}


def close(app,timeout=8):
    from .portable_runtime import request
    state=inspect(app)
    if state['cli']:return 'CLI не закрывается этим действием.'
    items=state['processes']
    if any(item['uid']!=os.getuid() for item in items):raise RuntimeError('Обнаружены процессы другого пользователя. Закройте их вручную; действие отменено.')
    if request(app):request(app,'stop')
    for item in reversed(items):
        current=inventory().get(item['pid'])
        if current and current['path']==item['path'] and current['uid']==os.getuid():
            try:os.kill(item['pid'],signal.SIGTERM)
            except ProcessLookupError:pass
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if not inspect(app)['processes']:return 'Процессы приложения закрыты.'
        time.sleep(.15)
    remaining=inspect(app)['processes']
    if remaining:raise RuntimeError('Приложение не подтвердило выход. Сохраните файлы и закройте его вручную; запуск или патч не выполнены.')
    return 'Процессы приложения закрыты.'
