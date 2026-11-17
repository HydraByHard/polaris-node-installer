import contextlib,io,unittest
from polaris_node.cli import parser,read_token
class CLITests(unittest.TestCase):
 def test_default_is_install(self):self.assertEqual(parser().parse_args([]).command,'install')
 def test_secret_argument_never_echoed(self):
  out=io.StringIO()
  with contextlib.redirect_stderr(out):
   with self.assertRaises(SystemExit):parser().parse_args(['--token','SENTINEL_SECRET'])
  self.assertNotIn('SENTINEL_SECRET',out.getvalue())
 def test_token_from_fd_not_environment(self):
  import os
  r,w=os.pipe();os.write(w,b'synthetic-test-token\n');os.close(w)
  try:self.assertEqual(read_token(r),'synthetic-test-token')
  finally:os.close(r)
