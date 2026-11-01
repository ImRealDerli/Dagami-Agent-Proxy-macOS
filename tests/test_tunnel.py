import unittest
import socket
import threading
from devproxy_pkg.core.profile import ProxyProfile
from devproxy_pkg.core.tunnel import LocalTunnel


class TestLocalTunnel(unittest.TestCase):
    def test_tunnel_start_and_bind(self):
                                     
        p = ProxyProfile(name="test", protocol="http", host="127.0.0.1", port=18888)
        tunnel = LocalTunnel(p, bind_host="127.0.0.1", bind_port=0)
        port = tunnel.start()
        self.assertGreater(port, 1024)
        self.assertTrue(tunnel.is_running)

                                                  
        sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
        sock.settimeout(5.0)
                                                                                                   
        sock.sendall(b"CONNECT dummy.domain:443 HTTP/1.1\r\nHost: dummy.domain:443\r\n\r\n")
        resp = sock.recv(1024)
        sock.close()
        tunnel.stop()

        self.assertIn(b"502 Bad Gateway", resp)


if __name__ == "__main__":
    unittest.main()
