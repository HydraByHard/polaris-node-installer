import json,os,pathlib,subprocess,tempfile,unittest
from unittest.mock import patch
from polaris_node.core import PolarisError,atomic_write
from polaris_node.system import System
from polaris_node.render import units,compose_config

class ReviewRegressionTests(unittest.TestCase):
 def test_ancestor_symlink_cannot_overwrite_foreign_file(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d);(p/'foreign').mkdir();(p/'foreign'/'key').write_text('original');(p/'managed').mkdir();(p/'managed'/'tls').symlink_to(p/'foreign',target_is_directory=True)
   with self.assertRaises(PolarisError):atomic_write(p/'managed/tls/key','replacement')
   self.assertEqual((p/'foreign/key').read_text(),'original')
 def test_boot_firewall_waits_for_tmpfiles(self):
  text=units({},'a'*32)['polaris-node-firewall.service'];self.assertIn('systemd-tmpfiles-setup.service',text)
 def test_tls_mount_follows_complete_directory_generation(self):
  c={'tls_mode':'provided'};cfg=compose_config(c,'a'*32,True);self.assertIn('/opt/polaris-node/tls:/etc/polaris-tls:ro',cfg['services']['gateway']['volumes'])
 def test_pending_publication_prevents_runtime_removal(self):
  class Store:
   data={'config':{},'install_id':'a'*32,'published':False,'publication_intent':{'phase':'host_pending'},'stages':{}}
  system=System(Store());system.snapshot=lambda: 'must-not-run'
  with self.assertRaises(PolarisError):system.remove(True)
 def test_pair_interruption_preserves_active_pair(self):
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d);(root/'tls/live').mkdir(parents=True);(root/'tls/archive').mkdir();(root/'tls/live/fullchain.pem').write_bytes(b'old-cert');(root/'tls/live/privkey.pem').write_bytes(b'old-key');(root/'tls/live/fullchain.pem').chmod(0o600);(root/'tls/live/privkey.pem').chmod(0o600)
   class Store:
    data={'config':{},'install_id':'a'*32,'stages':{}}
    def checkpoint(s,*args):pass
   system=System(Store());system.validate_tls_pair=lambda *a: None
   def interrupt(path,data,*args):
    if pathlib.Path(path).name=='privkey.pem':raise OSError('injected disk failure')
    atomic_write(path,data,*args)
   with patch('polaris_node.system.ROOT',root),patch('polaris_node.system.atomic_write',side_effect=interrupt):
    with self.assertRaises((OSError,PolarisError)):system.deploy_tls(b'new-cert',b'new-key')
   self.assertEqual((root/'tls/live/fullchain.pem').read_bytes(),b'old-cert');self.assertEqual((root/'tls/live/privkey.pem').read_bytes(),b'old-key')
 def test_failed_reload_restores_complete_pair(self):
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d);(root/'tls/live').mkdir(parents=True);(root/'tls/archive').mkdir()
   for file in ('fullchain.pem','privkey.pem'):(root/'tls/live'/file).write_bytes(b'old-'+file.encode());(root/'tls/live'/file).chmod(0o600)
   class Store:
    data={'config':{},'install_id':'a'*32,'stages':{}}
    def checkpoint(s,*args):pass
   system=System(Store());system.validate_tls_pair=lambda *a:None
   system.reload_gateway=lambda: (_ for _ in ()).throw(PolarisError('reload failed'))
   with patch('polaris_node.system.ROOT',root):
    with self.assertRaises(PolarisError):system.deploy_tls(b'new-cert',b'new-key')
   for file in ('fullchain.pem','privkey.pem'):self.assertEqual((root/'tls/live'/file).read_bytes(),b'old-'+file.encode())
 def test_compose_only_plan_rejects_engine_replacement(self):
  from polaris_node.system import validate_compose_plan
  for plan in ['Inst docker-ce [29.9.2] (29.9.3 Docker)\nInst docker-compose-plugin (2.40.3 Docker)','Remv docker.io [29.0]','Inst containerd.io (2.2.6 Docker)']:
   with self.assertRaises(PolarisError):validate_compose_plan(plan)
  validate_compose_plan('Inst docker-compose-plugin (2.40.3 Docker)\nConf docker-compose-plugin (2.40.3 Docker)')
 def test_restore_activation_enables_and_checks_acme_timer(self):
  from polaris_node.cli import activate_runtime
  class Recorder:
   def __init__(s):s.calls=[]
   def run(s,args,**kw):s.calls.append(args);return ''
  recorder=Recorder();activate_runtime({'tls_mode':'acme'},restart=True,runner=recorder)
  self.assertIn(['systemctl','enable','--now','polaris-node-renew.timer'],recorder.calls)
  self.assertIn(['systemctl','is-active','--quiet','polaris-node-renew.timer'],recorder.calls)
  self.assertIn(['systemctl','restart','polaris-node-firewall.service','polaris-node.service'],recorder.calls)
 def test_docker_key_bundle_cannot_add_another_trusted_primary(self):
  from polaris_node.system import validate_docker_key
  from polaris_node.core import PINS
  good='pub:-:4096:1:test:0:::::\nfpr:::::::::'+PINS['docker_gpg_fingerprint']+':\nsub::::::::::\nfpr:::::::::SUBKEY:'
  validate_docker_key(good)
  with self.assertRaises(PolarisError):validate_docker_key(good+'\npub::::::::::\nfpr:::::::::EVIL:')
 def test_firewall_audit_rejects_preceding_accept(self):
  from polaris_node.system import first_hook_matches,firewall_commands
  import shlex
  command=firewall_commands({'api_port':2222,'xray_port':8082,'http_port':80,'vpn_port':443},'a'*32)[0]
  rule='-A INPUT '+shlex.join(command[5:])
  self.assertTrue(first_hook_matches('-P INPUT ACCEPT\n'+rule,command))
  self.assertFalse(first_hook_matches('-P INPUT ACCEPT\n-A INPUT -j ACCEPT\n'+rule,command))
