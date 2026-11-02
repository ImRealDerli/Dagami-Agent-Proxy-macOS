import os,socket,ssl,subprocess,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg.core.tls_channel import TLSChannel,wrap_tls


class TLSChannelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();root=Path(cls.temp.name);cls.cert=root/'cert.pem';key=root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cls.cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],check=True,capture_output=True)
        cls.server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);cls.server_context.load_cert_chain(cls.cert,key)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def pair(self):
        first,second=socket.socketpair();first.settimeout(8);second.settimeout(8);accepted=[];errors=[]
        def accept():
            try:accepted.append(TLSChannel(self.server_context.wrap_socket(first,server_side=True)))
            except BaseException as error:errors.append(error)
        worker=threading.Thread(target=accept);worker.start()
        context=ssl.create_default_context(cafile=str(self.cert))
        client=wrap_tls(context,second,'localhost');worker.join(8)
        if errors:raise errors[0]
        return client,accepted[0]
    def test_large_bidirectional_transfer_preserves_bytes(self):
        client,server=self.pair();up=os.urandom(2*1024*1024);down=os.urandom(2*1024*1024);errors=[];seen={}
        def send(peer,data):
            try:peer.sendall(data)
            except BaseException as error:errors.append(error)
        def receive(peer,size,key):
            try:
                data=bytearray()
                while len(data)<size:
                    chunk=peer.recv(min(8192,size-len(data)))
                    if not chunk:raise ConnectionError('Unexpected fixture EOF')
                    data.extend(chunk)
                seen[key]=bytes(data)
            except BaseException as error:errors.append(error)
        threads=[threading.Thread(target=send,args=(client,up)),threading.Thread(target=send,args=(server,down)),threading.Thread(target=receive,args=(server,len(up),'up')),threading.Thread(target=receive,args=(client,len(down),'down'))]
        try:
            for worker in threads:worker.start()
            for worker in threads:worker.join(12)
            self.assertFalse(any(worker.is_alive() for worker in threads));self.assertEqual([],errors)
            self.assertEqual(up,seen['up']);self.assertEqual(down,seen['down'])
        finally:
            client.close();server.close()
            for worker in threads:worker.join(2)
    def test_read_timeout_and_close_interrupt_waiting_reader(self):
        client,server=self.pair();errors=[]
        try:
            client.settimeout(.08)
            with self.assertRaises(socket.timeout):client.recv(1)
            client.settimeout(None)
            def read():
                try:client.recv(1)
                except OSError:errors.append('closed')
            worker=threading.Thread(target=read);worker.start();time.sleep(.03);client.close();worker.join(1)
            self.assertFalse(worker.is_alive());self.assertEqual(['closed'],errors)
        finally:client.close();server.close()
    def test_invalid_certificate_is_still_rejected(self):
        first,second=socket.socketpair();first.settimeout(2);second.settimeout(2)
        def accept():
            try:self.server_context.wrap_socket(first,server_side=True).close()
            except ssl.SSLError:pass
            finally:first.close()
        worker=threading.Thread(target=accept);worker.start()
        try:
            with self.assertRaises(ssl.SSLCertVerificationError):wrap_tls(ssl.create_default_context(),second,'localhost')
        finally:second.close();worker.join(3)

    def test_half_close_does_not_turn_tls_reads_into_raw_ciphertext(self):
        client,server=self.pair()
        try:
            client.sendall(b'fixture request');client.shutdown(socket.SHUT_WR)
            self.assertEqual(b'fixture request',server.recv(1024))
            server.sendall(b'fixture response')
            self.assertEqual(b'fixture response',client.recv(1024))
        finally:client.close();server.close()
