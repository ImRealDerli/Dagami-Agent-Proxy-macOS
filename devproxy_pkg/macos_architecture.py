import functools,platform,struct,subprocess,sys
from pathlib import Path


@functools.lru_cache(maxsize=1)
def host_architecture():
    try:
        result=subprocess.run(['/usr/sbin/sysctl','-n','hw.optional.arm64'],capture_output=True,text=True,timeout=3)
        if result.returncode==0 and result.stdout.strip()=='1':return 'arm64'
    except (OSError,subprocess.SubprocessError):pass
    return platform.machine()


def executable_architectures(path):
    try:
        with Path(path).open('rb') as stream:data=stream.read(4096)
    except OSError:return set()
    if len(data)<8:return set()
    magic=data[:4];types={0x01000007:'x86_64',0x0100000c:'arm64',7:'i386',12:'arm'}
    if magic in (b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xfe\xed\xfa\xce'):
        endian='<' if magic[:1] in (b'\xcf',b'\xce') else '>'
        cpu=struct.unpack_from(endian+'I',data,4)[0];return {types.get(cpu,'CPU '+hex(cpu))}
    if magic in (b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf',b'\xbe\xba\xfe\xca',b'\xbf\xba\xfe\xca'):
        endian='>' if magic[:1]==b'\xca' else '<';count=struct.unpack_from(endian+'I',data,4)[0]
        size=32 if magic in (b'\xca\xfe\xba\xbf',b'\xbf\xba\xfe\xca') else 20
        if not 1<=count<=64 or len(data)<8+count*size:return set()
        return {types.get(cpu,'CPU '+hex(cpu)) for cpu in (struct.unpack_from(endian+'I',data,8+i*size)[0] for i in range(count))}
    return set()


def compatibility_error(path,host=None):
    if sys.platform!='darwin':return None
    host=host or host_architecture();arches=executable_architectures(path)
    if not arches or host in arches or host=='arm64' and 'x86_64' in arches:return None
    label='Apple Silicon (ARM64)' if arches=={'arm64'} else ', '.join(sorted(arches))
    return 'Несовместимая архитектура: '+Path(path).name+' собран для '+label+', а этот Mac использует '+('Intel (x86_64)' if host=='x86_64' else host)+'. Прокси-патч не может изменить архитектуру приложения.'


def require_compatible(path):
    error=compatibility_error(path)
    if error:raise RuntimeError(error)
