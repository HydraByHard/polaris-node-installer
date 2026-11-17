#!/usr/bin/env python3
"""Deterministic self-contained release; never include working credentials/labs."""
import argparse,base64,hashlib,io,json,pathlib,stat,tarfile,zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1]

def build(output):
    output.mkdir(parents=True,exist_ok=True)
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9)as archive:
        files={str(p.relative_to(ROOT/'src')):p.read_bytes()for p in sorted((ROOT/'src/polaris_node').iterdir())if p.suffix in ('.py','.json')}
        files['__main__.py']=b'from polaris_node.cli import entry\nraise SystemExit(entry())\n'
        for name,data in sorted(files.items()):
            item=zipfile.ZipInfo(name,(2026,1,1,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED;item.external_attr=0o644<<16;archive.writestr(item,data)
    blob=buffer.getvalue();digest=hashlib.sha256(blob).hexdigest()
    shell=(ROOT/'bootstrap.sh.in').read_text().replace('PAYLOAD_HASH',digest)
    encoded=base64.b64encode(blob).decode();shell+='\n'.join(encoded[i:i+76]for i in range(0,len(encoded),76))+'\n'
    p=output/'polaris-install.sh';p.write_text(shell);p.chmod(0o755)
    sha=hashlib.sha256(p.read_bytes()).hexdigest();(output/'SHA256SUMS').write_text(sha+'  polaris-install.sh\n')
    version=json.loads((ROOT/'src/polaris_node/pins.json').read_text())['installer']
    print(json.dumps({'version':version,'installer':str(p),'sha256':sha,'embedded_sha256':digest}))
    return p
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,default=ROOT/'dist');a=p.parse_args();build(a.output)
