import os,sys,json,http.client

def main():
    urls=[value for value in sys.argv[1:] if value.startswith('https://')]
    if not urls:return 1
    port=int(os.environ['DAGAMI_AUTH_PORT']);token=os.environ['DAGAMI_AUTH_TOKEN']
    connection=http.client.HTTPConnection('127.0.0.1',port,timeout=8)
    try:
        connection.request('POST','/capture',json.dumps({'url':urls[-1]}).encode(),{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        response=connection.getresponse();response.read(16384)
        return 0 if response.status==200 else 1
    finally:connection.close()

if __name__=='__main__':raise SystemExit(main())
