import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

def main():
    desktop=len(sys.argv)>1 and sys.argv[1]=='antigravity-desktop'
    try:
        from devproxy_pkg.session_telemetry import receive,clean_status
        data=sys.stdin.buffer.read(262145)
        if len(data)>262144:return
        payload=json.loads(data);path=os.environ.get('DAGAMI_SESSION_STATUS_PATH')
        if path:receive(sys.argv[1],sys.argv[2],payload,path)
        if sys.argv[2]=='status':
            safe=clean_status(sys.argv[1],payload);model=safe.get('model','');context=safe.get('contextUsed')
            print(model+(' · контекст '+str(round(context))+'%' if context is not None else ''))
    except Exception:pass
    finally:
        if desktop:print('{}')

if __name__=='__main__':main()
