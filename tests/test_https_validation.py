import unittest
from unittest.mock import patch
from devproxy_pkg.core.profile import ProxyProfile
from devproxy_pkg.core.validator import ProxyValidator

class HttpsValidationTests(unittest.TestCase):
    def test_https_proxy_preserves_outer_tls_using_bridge(self):
        profile=ProxyProfile.parse('https://fixture:password@proxy.example:443')
        with patch('devproxy_pkg.core.tunnel.LocalTunnel') as tunnel,patch.object(ProxyValidator,'_test_http_connect',return_value=(True,True,True,None)) as connect:
            tunnel.return_value.start.return_value=12345
            self.assertEqual((True,True,True,None),ProxyValidator.test_http_proxy(profile,'target.example',443))
            local=connect.call_args.args[0]
            self.assertEqual(('http','127.0.0.1',12345),(local.protocol,local.host,local.port))
            self.assertIsNone(local.password);tunnel.assert_called_once_with(profile);tunnel.return_value.stop.assert_called_once()
    def test_failed_https_probe_closes_bridge(self):
        with patch('devproxy_pkg.core.tunnel.LocalTunnel') as tunnel,patch.object(ProxyValidator,'_test_http_connect',side_effect=OSError('fixture')):
            tunnel.return_value.start.return_value=12345
            with self.assertRaises(OSError):ProxyValidator.test_http_proxy(ProxyProfile.parse('https://proxy.example:443'))
            tunnel.return_value.stop.assert_called_once()
    def test_503_and_tls_errors_are_reported_per_target(self):
        targets=[('First','first.example',443),('Second','second.example',443)]
        with patch.object(ProxyValidator,'test_tcp_connect',return_value=(True,1,None)),patch.object(ProxyValidator,'test_http_proxy',side_effect=[(False,False,False,'Proxy returned HTTP 503'),(False,False,False,'Strict TLS Verification Failed')]):
            result=ProxyValidator.validate(ProxyProfile.parse('http://proxy.example:8080'),targets)
        self.assertFalse(result.overall_success);self.assertEqual(2,len(result.errors))
        self.assertIn('503',result.errors[0]);self.assertIn('first.example',result.errors[0]);self.assertIn('Strict TLS',result.errors[1])
