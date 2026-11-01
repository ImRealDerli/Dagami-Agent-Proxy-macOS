
from pathlib import Path
import hashlib
import os
import plistlib
import shutil
import subprocess
import uuid
import re
import struct
from .core.recovery import StateManager,get_devproxy_state_path
from .core.process_env import external_environment

PATTERNS=(b'\n\x10ineligible_tiers',b'R\x0fineligibleTiers',b'\n\nineligible\x18\x03',b'R\nineligible',b'name=ineligible,proto3',b'name=ineligible_tiers,',b'json=ineligibleTiers,',b'json:"ineligible_tiers,')


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def cli_gate(data):
    if len(data)<32 or data[:4]!=b'\xcf\xfa\xed\xfe' or struct.unpack_from('<I',data,4)[0]!=0x01000007:
        raise ValueError('CLI-патч подтверждён только для совместимого Mach-O x86_64. Файл не изменён.')
    if b'prompt-interactive' not in data or b'Eligibility check failed:' not in data or not (b'Go build ID:' in data or b'Go buildinf:' in data):
        raise ValueError('Неизвестная структура CLI. Файл не изменён.')
    count,size=struct.unpack_from('<II',data,16)
    if not 1<=count<=256 or 32+size>len(data):raise ValueError('Повреждён заголовок Mach-O.')
    sections=[];cursor=32;end=32+size
    for _ in range(count):
        if cursor+8>end:raise ValueError('Обрезанный Mach-O.')
        cmd,length=struct.unpack_from('<II',data,cursor)
        if length<8 or cursor+length>end:raise ValueError('Некорректная команда Mach-O.')
        if cmd==0x19:
            if length<72:raise ValueError('Некорректный сегмент Mach-O.')
            nsects=struct.unpack_from('<I',data,cursor+64)[0]
            if 72+80*nsects>length:raise ValueError('Некорректные секции Mach-O.')
            for i in range(nsects):
                at=cursor+72+80*i
                if data[at:at+16].rstrip(b'\0')!=b'__text' or data[at+16:at+32].rstrip(b'\0')!=b'__TEXT':continue
                length_bytes=struct.unpack_from('<Q',data,at+40)[0];offset=struct.unpack_from('<I',data,at+48)[0]
                flags=struct.unpack_from('<I',data,at+64)[0]
                if not flags&0x80000400 or offset+length_bytes>len(data):raise ValueError('Некорректная исполняемая секция.')
                sections.append((offset,offset+length_bytes))
        cursor+=length
    signature=rb'\x48\x85\xc0\x0f\x84....\x80\x78\x08\x00\x0f\x85....\x48\x8b\x50\x50\x4c\x8d\x1d'
    sites=[]
    for start,limit in sections:
        for match in re.finditer(signature,data[start:limit],re.S):
            pos=start+match.start();a=pos+9+struct.unpack_from('<i',data,pos+5)[0];b=pos+19+struct.unpack_from('<i',data,pos+15)[0]
            if a==b and pos+19<=a<min(limit,pos+4096):sites.append(pos+9)
    if len(sites)!=1:raise ValueError('Неизвестная или неоднозначная региональная проверка CLI. Файл не изменён.')
    return sites[0]


def patch_data(data,cli=False):
    gate=cli_gate(data) if cli else None
                                                                                   
    if any(data.count(pattern)!=1 for pattern in PATTERNS):
        raise ValueError('Несовместимые или частично изменённые protobuf-сигнатуры. Файл не изменён.')
    if data.count(b'https_proxy')>32:
        raise ValueError('Неоднозначные proxy-сигнатуры. Файл не изменён.')
    result=data
    for pattern in PATTERNS:result=result.replace(pattern,pattern.replace(b'ineligible',b'dpeligible'))
    result=result.replace(b'https_proxy',b'AG_LS_PROXY')
    if gate is not None:result=result[:gate]+b'\x48\x85\xc0\x90'+result[gate+4:]
    return result


def managed_root():
    return Path(get_devproxy_state_path()).parent/'prepared-macos'


def record(app):return StateManager.load_state().get('prepared_macos',{}).get(app)


def checked_executable(app,verify=True):
    item=record(app)
    if not item:return None
    root=managed_root().resolve();bundle=Path(item['bundle'])
    if not bundle.resolve().is_relative_to(root) or bundle.is_symlink():raise RuntimeError('Повреждён путь подготовленного приложения.')
    if not Path(item['executable']).is_file():raise RuntimeError('Подготовленное приложение отсутствует. Выполните откат.')
    if verify:
        for relative,expected in item['backends'].items():
            path=bundle/relative
            if path.is_symlink() or not path.is_file() or digest(path)!=expected:
                raise RuntimeError('SHA-256 подготовленного backend не совпал. Подготовка не считается действующей; выполните откат.')
    return item['executable']


def codesign(path,*options):
    try:
        subprocess.run(['/usr/bin/codesign',*options,str(path)],check=True,env=external_environment(),capture_output=True)
    except subprocess.CalledProcessError as exc:
        detail=(exc.stderr or b'').decode('utf-8','replace').strip()
        raise RuntimeError('Ошибка подписи '+Path(path).name+': '+(detail or 'codesign завершился с кодом '+str(exc.returncode))) from None


def sign_bundle(target,backends):
    for path in backends:
        codesign(path,'--force','--sign','-','--preserve-metadata=entitlements,runtime')
        codesign(path,'--verify','--strict')
    codesign(target,'--force','--deep','--sign','-','--preserve-metadata=entitlements,runtime')
    codesign(target,'--verify','--deep','--strict')


def prepare(app):
    from .portable_runtime import app_adapter,executable,require_stopped,request,session_lock
    if app not in ('antigravity','agy'):raise ValueError('Бинарная подготовка доступна для совместимого Antigravity.')
    with session_lock('backend'):
        if request(app):raise RuntimeError('Сначала остановите управляемую сессию Antigravity.')
        if record(app):
            checked_executable(app);return 'Подготовка уже действует. Для новой версии сначала выполните откат.'
        source=Path(executable(app_adapter(app))).resolve();require_stopped(str(source))
        bundle=next((p for p in source.parents if p.suffix=='.app'),None)
        if bundle is None:
            if app!='agy':raise ValueError('Не найден bundle Antigravity.')
            patched=patch_data(source.read_bytes(),cli=True)
            root=managed_root();root.mkdir(parents=True,exist_ok=True,mode=0o700)
            target=root/uuid.uuid4().hex/'CLI';target.mkdir(parents=True,mode=0o700)
            dest=target/'agy'
            try:
                dest.write_bytes(patched);dest.chmod(0o700)
                codesign(dest,'--force','--sign','-')
                codesign(dest,'--verify','--strict')
                state=StateManager.load_state();state.setdefault('prepared_macos',{})[app]={'original':str(source),'original_sha256':digest(source),'executable':str(dest),'bundle':str(target),'backends':{'agy':digest(dest)}}
                StateManager.save_state(state)
            except BaseException:shutil.rmtree(target.parent);raise
            return 'Патч CLI готов: локальная проверка, восемь protobuf-полей и proxy-env. Подпись копии проверена; оригинал не изменён. Запустите agy через Dagami. Доступность API проверяется отдельно.'

        candidates=[p for p in (bundle/'Contents'/'Resources').rglob('language_server*') if p.is_file() and not p.is_symlink()]
        if not candidates:raise ValueError('В приложении не найден language_server.')
                                                                      
        for path in candidates:
            if path.read_bytes()[:4] not in (b'\xcf\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xfe\xed\xfa\xcf'):
                raise ValueError('Backend не является поддерживаемым Mach-O.')
            patch_data(path.read_bytes())
        root=managed_root();root.mkdir(parents=True,exist_ok=True,mode=0o700)
        target=root/uuid.uuid4().hex/bundle.name;target.parent.mkdir(mode=0o700)
        try:
            subprocess.run(['/usr/bin/ditto',str(bundle),str(target)],check=True,env=external_environment(),capture_output=True)
            from .macos_auth_patch import patch_bundle
            auth_files=patch_bundle(target)
            for path in candidates:
                dest=target/path.relative_to(bundle);patched=patch_data(dest.read_bytes());mode=dest.stat().st_mode
                dest.chmod(mode|0o200);dest.write_bytes(patched);dest.chmod(mode)
                                                                   
            sign_bundle(target,[target/path.relative_to(bundle) for path in candidates])
            prepared=str(target/source.relative_to(bundle))
            hashes={p.relative_to(bundle).as_posix():digest(target/p.relative_to(bundle)) for p in candidates}
            hashes.update({name:digest(target/name) for name in auth_files})
            state=StateManager.load_state();state.setdefault('prepared_macos',{})[app]={'original':str(source),'executable':prepared,'bundle':str(target),'backends':hashes,'auth_routing':bool(auth_files),'auth_capture':2 if auth_files else 0}
            StateManager.save_state(state)
        except BaseException:
            shutil.rmtree(target.parent);raise
        return 'Готово: восемь protobuf-изменений и приватная proxy-env; подпись копии проверена. Оригинал сохранён. Запускайте через Dagami.'


def restore(app):
    from .portable_runtime import request,require_stopped,session_lock
    with session_lock('backend'):
        item=record(app)
        if not item:return 'Бинарная подготовка не применялась.'
        if request(app):raise RuntimeError('Сначала остановите сессию.')
        checked_executable(app)
        require_stopped(item['executable'])
        if not Path(item['original']).is_file():raise RuntimeError('Оригинал приложения отсутствует. Запись отката сохранена.')
                                                                                        
        state=StateManager.load_state();del state['prepared_macos'][app];StateManager.save_state(state)
        try:shutil.rmtree(Path(item['bundle']).parent)
        except OSError as exc:raise RuntimeError('Запуск возвращён к оригиналу; не удалось удалить приватную копию: '+str(exc))
        return 'Запуск возвращён к установленному оригиналу. Приватная подготовленная копия удалена.'
