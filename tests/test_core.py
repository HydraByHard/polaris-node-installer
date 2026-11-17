import json,os,pathlib,tempfile,unittest
from polaris_node.core import PolarisError,normalize_config,StateStore,redact,retry_config

class ConfigTests(unittest.TestCase):
 def test_defaults_and_name(self):
  c=normalize_config({'name':'finland-01','country':'Finland','domain':'FI1.followyourpolaris.space','public_ipv4':'192.0.2.1','panel_ipv4':['208.123.185.211']})
  self.assertEqual(c['domain'],'fi1.followyourpolaris.space');self.assertEqual(c['country'],'FI');self.assertEqual(c['api_port'],2222)
 def test_protected_dns_never_changed(self):
  for d in ['panel.followyourpolaris.space','sub.followyourpolaris.space','backup.followyourpolaris.space']:
   with self.assertRaises(PolarisError):normalize_config({'name':'node-01','domain':d})
 def test_injection_and_secret_config_rejected(self):
  for patch in [{'name':'x; reboot'},{'domain':'x/../../etc/passwd'},{'token':'do-not-store'},{'api_port':22},{'api_port':443}]:
   with self.assertRaises(PolarisError):normalize_config({'name':'node-01','domain':'new.example.org',**patch})
 def test_https_authority_only(self):
  for url in ['http://panel.example.org','https://user:password@panel.example.org','https://panel.example.org/?token=x']:
   with self.assertRaises(PolarisError):normalize_config({'name':'node-01','domain':'new.example.org','panel_url':url})

class RetryConfigTests(unittest.TestCase):
 def test_correct_source_ip_without_identity_change(self):
  self.assertEqual(retry_config({'name':'node','panel_ipv4':['10.0.2.2']},{'name':'node','panel_ipv4':['172.18.0.5']}),{'name':'node','panel_ipv4':['172.18.0.5']})
 def test_other_changes_never_adopted(self):
  with self.assertRaises(PolarisError):retry_config({'domain':'old.example.org'},{'domain':'other.example.org'})

class StateTests(unittest.TestCase):
 def test_atomic_state_and_retry_identity(self):
  with tempfile.TemporaryDirectory() as d:
   s=StateStore(pathlib.Path(d)/'state');s.create({'name':'node-01'});identity=s.data['install_id'];s.data['stages']['a']=True;s.save();s.close()
   t=StateStore(pathlib.Path(d)/'state');self.assertEqual(t.data['install_id'],identity);self.assertTrue(t.data['stages']['a']);self.assertEqual((t.path/'state.json').stat().st_mode&0o777,0o600);t.close()
 def test_symlink_refused(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);(p/'foreign').mkdir();(p/'state').symlink_to(p/'foreign')
   with self.assertRaises(PolarisError):StateStore(p/'state')
 def test_concurrent_lock_refused(self):
  with tempfile.TemporaryDirectory() as d:
   a=StateStore(pathlib.Path(d)/'state')
   with self.assertRaises(PolarisError):StateStore(pathlib.Path(d)/'state')
   a.close()
 def test_failed_atomic_replace_keeps_old_state(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   s=StateStore(pathlib.Path(d)/'state');s.create({});old=(s.path/'state.json').read_bytes();s.data['stages']['not_committed']=True
   with patch('os.replace',side_effect=OSError('injected')):
    with self.assertRaises(OSError):s.save()
   self.assertEqual((s.path/'state.json').read_bytes(),old);s.close()
 def test_never_persist_api_credential(self):
  with tempfile.TemporaryDirectory() as d:
   s=StateStore(pathlib.Path(d)/'state');s.create({});s.data['api_token']='not-allowed'
   with self.assertRaises(PolarisError):s.save()
   s.close()
 def test_redacts_tokens_and_private_material(self):
  text='tokenABC ' + 'eyJhbGciOiJIUzI1NiJ9.abcdefghijk.abcdefghijklmnop'+'\n-----BEGIN PRIVATE KEY-----\nSECRET\n-----END PRIVATE KEY-----'
  result=redact(text,['tokenABC']);self.assertNotIn('tokenABC',result);self.assertNotIn('SECRET',result);self.assertNotIn('eyJhbG',result)
