import copy,io,json,pathlib,tarfile,tempfile,unittest
from unittest.mock import patch
from polaris_node.core import PolarisError,normalize_config
from polaris_node.cli import runtime_restore,parser

class RestoreTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name);self.config=self.root/'config';self.config.mkdir();self.cli=self.root/'cli';self.statepath=self.root/'state';(self.statepath/'backups').mkdir(parents=True)
  self.data={'schema':1,'install_id':'a'*32,'config':normalize_config({'name':'finland-01','domain':'fi.example.org'}),'resources':{'host_id':'test-owned'},'stages':{},'published':False}
  class Store:
   def save(s):pass
   def close(s):pass
  class Recorder:
   def run(s,*a,**kw):return ""
  class System:
   def firewall(s):pass
   def compose(s,*a,**kw):pass
   def install_units(s):pass
  self.system=System();self.system.r=Recorder();self.system.store=Store();self.system.store.path=self.statepath;self.system.store.data=copy.deepcopy(self.data);self.system.state=self.system.store.data;self.system.identity='a'*32;self.system.c=self.data['config']
  self.patchers=[patch('polaris_node.cli.ROOT',self.config),patch('polaris_node.cli.CLI',self.cli)]
  for p in self.patchers:p.start();self.addCleanup(p.stop)
 def archive(self,members):
  p=self.statepath/'backups'/'owned.tar.gz'
  with tarfile.open(p,'w:gz')as tar:
   for name,content in members:
    raw=content.encode();item=tarfile.TarInfo(name);item.size=len(raw);tar.addfile(item,io.BytesIO(raw))
  p.chmod(0o600);return p.name
 def valid_members(self):return [('state.json',json.dumps(self.data)),('config/compose.json','{}'),('config/node.env','SECRET_KEY=original\n'),('config/nginx/nginx.conf','owned'),('polaris-node','original script')]
 def test_duplicate_members_rejected_before_mutation(self):
  name=self.archive(self.valid_members()+[('state.json',json.dumps(self.data))])
  with self.assertRaises(PolarisError):runtime_restore(self.system,name)
  self.assertFalse((self.config/'compose.json').exists())
 def test_different_native_identity_rejected_before_mutation(self):
  (self.config/'node.env').write_text('SECRET_KEY=current\n');(self.config/'node.env').chmod(0o600)
  name=self.archive(self.valid_members())
  with self.assertRaises(PolarisError):runtime_restore(self.system,name)
  self.assertFalse((self.config/'compose.json').exists())
 def test_missing_runtime_member_rejected_before_mutation(self):
  name=self.archive([('state.json',json.dumps(self.data)),('config/compose.json','{}')])
  with self.assertRaises(PolarisError):runtime_restore(self.system,name)
  self.assertFalse((self.config/'compose.json').exists())
 def test_remote_state_cannot_be_rewound(self):
  self.system.store.data['published']=True;self.system.store.data['publication_record']={'squad_id':'owned-test'}
  name=self.archive(self.valid_members());runtime_restore(self.system,name)
  self.assertTrue(self.system.store.data['published']);self.assertEqual(self.system.store.data['publication_record'],{'squad_id':'owned-test'})
 def test_unpublish_command_available(self):self.assertEqual(parser().parse_args(['unpublish']).command,'unpublish')

 def test_snapshot_with_only_one_tls_file_is_rejected_before_mutation(self):
  self.data['stages']['tls']=True
  name=self.archive(self.valid_members()+[('config/tls/live/fullchain.pem','unpaired')])
  with self.assertRaises(PolarisError):runtime_restore(self.system,name)
  self.assertFalse((self.config/'compose.json').exists())
