import pathlib,tempfile,unittest
from unittest.mock import patch
from polaris_node.core import PolarisError
from polaris_node.system import Runner,parse_listeners,validate_os,check_resources,firewall_commands
class SystemTests(unittest.TestCase):
 def test_unsupported_os(self):
  for data in [{'ID':'debian','VERSION_ID':'12'},{'ID':'ubuntu','VERSION_ID':'20.04'}]:
   with self.assertRaises(PolarisError):validate_os(data,'x86_64')
 def test_two_ubuntu_versions(self):
  for version in ('22.04','24.04'):self.assertEqual(validate_os({'ID':'ubuntu','VERSION_ID':version},'x86_64'),version)
 def test_low_resources_stops(self):
  for args in [(512,2,10*1024**3),(2048,0,10*1024**3),(2048,2,1024**3)]:
   with self.assertRaises(PolarisError):check_resources(*args)
 def test_ip6_and_ipv4_ports_parse(self):
  s='tcp LISTEN 0 128 [::]:2222 [::]:* users:(("node",pid=99,fd=4))\ntcp LISTEN 0 128 127.0.0.1:8082 0.0.0.0:* users:(("xray",pid=100,fd=4))'
  self.assertEqual(parse_listeners(s),[(2222,{99}),(8082,{100})])
 def test_actual_ss_without_netid(self):
  s='LISTEN 0 4096 0.0.0.0:2222 0.0.0.0:* users:(("node",pid=300,fd=4))'
  self.assertEqual(parse_listeners(s),[(2222,{300})])
 def test_runner_does_not_leak_captured_secrets(self):
  with self.assertRaises(PolarisError)as e:Runner().run(['/bin/sh','-c','echo SUPERSECRET >&2; exit 2'])
  self.assertNotIn('SUPERSECRET',str(e.exception))
 def test_firewall_commands_scoped_v4v6(self):
  c={'api_port':2222,'xray_port':8082,'vpn_port':443,'http_port':80};cmds=firewall_commands(c,'1234567890abcdef1234567890abcdef')
  self.assertEqual([x[0]for x in cmds],['iptables','ip6tables']);self.assertTrue(all('-C'in x for x in cmds));self.assertFalse(any('-F'in x for x in cmds))

class XrayProcessProbeTests(unittest.TestCase):
 def test_docker_top_requires_pid_column(self):
  from polaris_node.system import System
  class Store:
   data={'config':{'domain':'node.example.org','xray_port':8082},'install_id':'1234567890abcdef1234567890abcdef','stages':{}}
   def checkpoint(self,*args):pass
  class DockerProbe:
   def run(self,args,*a,**kw):
    if 'top'in args:
     if args[-1]=='comm':raise PolarisError("Couldn't find PID field in ps output")
     return 'PID COMMAND\n100 rw-core'
    return 'Xray 26.11.9'
  System(Store(),DockerProbe()).check_xray()

class FirewallAuditTests(unittest.TestCase):
 def test_order_and_extra_accept_are_rejected(self):
  from polaris_node.system import rules_match
  expected='-A PNI_TEST -i lo -j ACCEPT\n-A PNI_TEST -p tcp --dport 2222 -j DROP\n-A PNI_TEST -j RETURN'
  canonical='-N PNI_TEST\n-A PNI_TEST -i lo -j ACCEPT\n-A PNI_TEST -p tcp -m tcp --dport 2222 -j DROP\n-A PNI_TEST -j RETURN'
  self.assertTrue(rules_match(expected,canonical))
  self.assertFalse(rules_match(expected,'-A PNI_TEST -j ACCEPT\n'+canonical))
  self.assertFalse(rules_match(expected,'-A PNI_TEST -j RETURN\n-A PNI_TEST -p tcp --dport 2222 -j DROP\n-A PNI_TEST -i lo -j ACCEPT'))
