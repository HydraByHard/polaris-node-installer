"""Xray26.11.9 trust-store contract, verified by the real private-CA fixture."""
import json,pathlib,tempfile,unittest
from unittest.mock import patch
from polaris_node.cli import test_traffic
from polaris_node.core import PolarisError

class TrafficTrustTests(unittest.TestCase):
 def test_probe_uses_host_ca_store_without_disabling_certificate_verification(self):
  with tempfile.TemporaryDirectory()as temp:
   folder=pathlib.Path(temp)
   cfg={'outbounds':[{'protocol':'vless','settings':{'vnext':[{'address':'node.pni.test','port':443,'users':[{'id':'synthetic-credential','encryption':'none'}]}]},'streamSettings':{'network':'xhttp','security':'tls','tlsSettings':{'serverName':'node.pni.test','alpn':['h2']},'xhttpSettings':{'mode':'packet-up'}}}]}
   source=folder/'input.json';source.write_text(json.dumps(cfg));source.chmod(0o600)
   class Provider:
    def __init__(s):s.tls=None;s.removed=False
    def run(s,args,**kwargs):
     if 'run'in args and '--entrypoint'in args:
      mount=next(value for value in args if value.startswith('type=bind,src=')and ',dst=/run/client.json,'in value)
      client=json.loads(pathlib.Path(mount.split('src=',1)[1].split(',dst=',1)[0]).read_text());s.tls=client['outbounds'][0]['streamSettings']['tlsSettings'];return 'container-created'
     if args[0]=='curl':
      # The pinned Xray defaults to embedded roots. The real fixture uses an
      # owner-trusted private CA; merely mounting the file does not select it.
      if not s.tls.get('useSystemCA'):raise PolarisError('x509: certificate signed by unknown authority')
      return '192.0.2.15'
     if 'rm'in args:s.removed=True
     return ''
   class Store:path=folder
   class System:c={'domain':'node.pni.test','vpn_port':443,'public_ipv4':'192.0.2.15'};identity='a'*32;store=Store()
   system=System();system.r=Provider()
   with patch('polaris_node.cli.socket.create_connection'):report=test_traffic(system,str(source))
   self.assertEqual(report['actual_vpn_traffic'],'PASS');self.assertTrue(system.r.removed)
   self.assertTrue(system.r.tls['useSystemCA']);self.assertFalse(system.r.tls.get('allowInsecure',False))
   self.assertEqual(json.loads(source.read_text()),cfg)
