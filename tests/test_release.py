import hashlib,importlib.util,pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pni_build',ROOT/'scripts/build-release.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class ReleaseTests(unittest.TestCase):
 def test_reproducible_embedded_release(self):
  with tempfile.TemporaryDirectory()as d:
   a=module.build(pathlib.Path(d)/'a');b=module.build(pathlib.Path(d)/'b');self.assertEqual(a.read_bytes(),b.read_bytes())
   r=subprocess.run(['bash',str(a),'--version'],capture_output=True,text=True);self.assertEqual(r.returncode,0);self.assertEqual(r.stdout.strip(),'1.0.0')
 def test_corrupt_payload_is_not_executed(self):
  with tempfile.TemporaryDirectory()as d:
   p=module.build(pathlib.Path(d));text=p.read_text();start=text.index('\n__POLARIS_PAYLOAD__\n')+len('\n__POLARIS_PAYLOAD__\n');text=text[:start]+('A'if text[start]!='A'else'B')+text[start+1:];p.write_text(text)
   r=subprocess.run(['bash',str(p),'--version'],capture_output=True,text=True);self.assertNotEqual(r.returncode,0);self.assertNotIn('1.0.0',r.stdout)
 def test_wrong_trusted_checksum_rejected(self):
  with tempfile.TemporaryDirectory()as d:
   p=module.build(pathlib.Path(d));r=subprocess.run(['sha256sum','-c','-'],input='0'*64+'  '+str(p)+'\n',capture_output=True,text=True);self.assertNotEqual(r.returncode,0)
 def test_detached_signature_valid_and_tamper_denied(self):
  with tempfile.TemporaryDirectory()as d:
   d=pathlib.Path(d);p=module.build(d);key=d/'key.pem';pub=d/'pub.pem';sig=d/'installer.sig'
   for args in [['openssl','genpkey','-algorithm','ED25519','-out',str(key)],['openssl','pkey','-in',str(key),'-pubout','-out',str(pub)],['openssl','pkeyutl','-sign','-rawin','-inkey',str(key),'-in',str(p),'-out',str(sig)]]:subprocess.run(args,capture_output=True,check=True)
   key.chmod(0o600)
   cmd=['openssl','pkeyutl','-verify','-rawin','-pubin','-inkey',str(pub),'-in',str(p),'-sigfile',str(sig)]
   self.assertEqual(subprocess.run(cmd,capture_output=True).returncode,0)
   p.write_bytes(p.read_bytes()+b'# tampered\n');self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)
 def test_download_failure_cannot_pass_trusted_hash(self):
  with tempfile.TemporaryDirectory()as d:
   # A closed loopback endpoint is deterministic and does not contact GitHub.
   p=pathlib.Path(d)/'installer.sh';r=subprocess.run(['curl','-fL','--connect-timeout','1','-o',str(p),'https://127.0.0.1:9/nonexistent'],capture_output=True)
   self.assertNotEqual(r.returncode,0);self.assertFalse(p.exists())
