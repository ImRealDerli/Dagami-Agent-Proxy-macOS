import concurrent.futures,ipaddress,socket,struct,threading,time,unittest
from unittest.mock import patch
from devproxy_pkg.core.smart_dns import Resolver


def reply(query,addresses):
    records=b''.join(b'\xc0\x0c'+struct.pack('!HHIH',1,1,120,4)+ipaddress.ip_address(address).packed for address in addresses)
    return query[:2]+struct.pack('!HHHHH',0x8180,1,len(addresses),0,0)+query[12:]+records


class DnsResilienceTests(unittest.TestCase):
    def test_rejected_address_uses_another_answer_without_new_dns_query(self):
        resolver=Resolver(['udp://fixture.example'])
        with patch('devproxy_pkg.core.smart_dns.exchange',side_effect=lambda endpoint,query,*args:reply(query,['8.8.8.8','8.8.4.4'])) as exchange:
            self.assertEqual('8.8.8.8',resolver.resolve('api.openai.com'));resolver.reject('api.openai.com','8.8.8.8')
            self.assertEqual('8.8.4.4',resolver.resolve('api.openai.com'));self.assertEqual(1,exchange.call_count)
    def test_all_rejected_answers_use_only_selected_backup_provider(self):
        resolver=Resolver(['udp://first.example','udp://backup.example'])
        def exchange(endpoint,query,*args):return reply(query,['8.8.8.8'] if 'first' in endpoint else ['1.1.1.1'])
        with patch('devproxy_pkg.core.smart_dns.exchange',side_effect=exchange) as run:
            self.assertEqual('8.8.8.8',resolver.resolve('api.anthropic.com'));resolver.reject('api.anthropic.com','8.8.8.8')
            self.assertEqual('1.1.1.1',resolver.resolve('api.anthropic.com'))
            self.assertEqual({'udp://first.example','udp://backup.example'},{call.args[0] for call in run.call_args_list})
    def test_concurrent_requests_share_one_dns_exchange(self):
        resolver=Resolver(['udp://fixture.example']);barrier=threading.Barrier(12)
        def exchange(endpoint,query,*args):time.sleep(.05);return reply(query,['8.8.8.8'])
        def resolve(_):barrier.wait();return resolver.resolve('chatgpt.com')
        with patch('devproxy_pkg.core.smart_dns.exchange',side_effect=exchange) as run,concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            self.assertEqual(['8.8.8.8']*12,list(pool.map(resolve,range(12))));self.assertEqual(1,run.call_count)
    def test_unavailable_primary_is_kept_in_reserve_for_new_hosts(self):
        resolver=Resolver(['udp://first.example','udp://backup.example']);seen=[]
        def exchange(endpoint,query,*args):
            seen.append(endpoint)
            if 'first' in endpoint:raise OSError('fixture unavailable')
            return reply(query,['8.8.8.8'])
        with patch('devproxy_pkg.core.smart_dns.exchange',side_effect=exchange):
            resolver.resolve('api.openai.com');resolver.resolve('api.anthropic.com')
        self.assertEqual(['udp://first.example','udp://backup.example','udp://backup.example'],seen)
    def test_provider_hostname_remains_a_fallback_after_seed_rotation(self):
        resolver=Resolver(['https://dns.dagami.ru/dns-query']);nodes=[]
        def exchange(endpoint,query,timeout,node):
            nodes.append(node)
            if node!='dns.dagami.ru':raise OSError('fixture stale seed')
            return reply(query,['8.8.8.8'])
        with patch('devproxy_pkg.core.smart_dns.exchange',side_effect=exchange):self.assertEqual('8.8.8.8',resolver.resolve('api.openai.com'))
        self.assertEqual('dns.dagami.ru',nodes[-1])
