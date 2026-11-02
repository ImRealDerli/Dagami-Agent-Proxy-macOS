import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

def main():
    desktop=len(sys.argv)>1 and sys.argv[1]=='antigravity-desktop'
    event=sys.argv[2] if len(sys.argv)>2 else ''
    try:
        from devproxy_pkg.session_telemetry import receive,clean_status
        data=sys.stdin.buffer.read(262145)
        if len(data)<=262144 and data.strip():
            payload=json.loads(data);path=os.environ.get('DAGAMI_SESSION_STATUS_PATH')
            if path and event:receive(sys.argv[1],event,payload,path)
            if event=='status':
                safe=clean_status(sys.argv[1],payload);model=safe.get('model','');context=safe.get('contextUsed')
                print(model+(' · контекст '+str(round(context))+'%' if context is not None else ''))
    except Exception:pass
    finally:
        if desktop:
            if event=='PreToolUse':print(json.dumps({'decision':'allow'}))
            else:print('{}')
        sys.stdout.flush()

if __name__=='__main__':main()
