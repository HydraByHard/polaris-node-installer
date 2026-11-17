import unittest
from polaris_node.render import xray_config,nginx_config,compose_config,firewall_rules,units
C={'name':'finland-01','domain':'fi1.example.org','api_port':2222,'vpn_port':443,'http_port':80,'xray_port':8082,'panel_ipv4':['208.123.185.211'],'panel_ipv6':[],'public_ipv4':'192.0.2.1','public_ipv6':None}
ID='1234567890abcdef1234567890abcdef'
class RenderTests(unittest.TestCase):
 def test_xray_loopback_transport_and_private_denials(self):
  c=xray_config(C,ID);i=c['inbounds'][0]
  self.assertEqual(i['listen'],'127.0.0.1');self.assertEqual(i['streamSettings']['xhttpSettings']['mode'],'packet-up');self.assertEqual(i['tag'],'PNI_1234567890ABCDEF');self.assertIn('fc00::/7',c['routing']['rules'][0]['ip'])
 def test_no_docker_published_ports_or_socket(self):
  c=compose_config(C,ID,False)
  for s in c['services'].values():
   self.assertEqual(s['network_mode'],'host');self.assertNotIn('ports',s);self.assertNotEqual(s['restart'],'unless-stopped');self.assertNotIn('/var/run/docker.sock',str(s))
 def test_tls_gateway_minimized_mounts(self):
  c=compose_config(C,ID,True);s=str(c['services']['gateway']['volumes']);self.assertNotIn('/accounts',s);self.assertNotIn(':/etc/letsencrypt:ro',s)
  n=nginx_config(C,ID,True);self.assertIn('http2 on',n);self.assertIn('location / { return 404; }',n);self.assertNotIn('proxy_pass http://0.0.0.0',n)
 def test_firewall_never_flushes_foreign_chains_or_ssh(self):
  for family in [4,6]:
   rules=firewall_rules(C,ID,family)
   self.assertNotIn('-F INPUT',rules);self.assertNotIn('--dport 22 ',rules);self.assertNotIn('-P ',rules)
   self.assertIn('-j DROP',rules);self.assertIn('-i lo -j ACCEPT',rules)
  self.assertIn('-s 208.123.185.211/32',firewall_rules(C,ID,4));self.assertNotIn('-s ',firewall_rules(C,ID,6))
 def test_boot_guards_own_project_without_global_docker_requires(self):
  u=units(C,ID);self.assertIn('polaris-node-firewall.service',u['polaris-node.service']);self.assertIn('PartOf=docker.service',u['polaris-node.service']);self.assertIn('WantedBy=multi-user.target docker.service',u['polaris-node.service']);self.assertNotIn('docker.service.d',str(u));self.assertIn('Persistent=true',u['polaris-node-renew.timer'])
