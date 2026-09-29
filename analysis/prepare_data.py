"""Verify public source hashes and unpack the compressed research data locally."""
from pathlib import Path
import gzip,hashlib,json
ROOT=Path(__file__).resolve().parents[1]
def main():
 records=json.loads((ROOT/'provenance/artifacts.json').read_text())
 for item in records:
  path=ROOT/item['published_path'];raw=path.read_bytes()
  assert hashlib.sha256(raw).hexdigest()==item['stored_sha256'], str(path)
  data=gzip.decompress(raw) if item['gzip'] else raw
  assert hashlib.sha256(data).hexdigest()==item['published_content_sha256'],str(path)
  if item['gzip']:
   rel=Path(item['published_path']).relative_to('data')
   if rel.parts[0]=='db':dest=ROOT/'build/db/csv'/rel.name.removesuffix('.gz')
   else:dest=ROOT/'build'/str(rel).removesuffix('.gz')
   dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
 db=json.loads((ROOT/'provenance/collection.json').read_text())['db']
 for table in db['relations']:
  f=ROOT/'build/db'/table['csv'];table['sha256']=hashlib.sha256(f.read_bytes()).hexdigest()
  table['bytes']=f.stat().st_size
 (ROOT/'build/db/manifest.json').write_text(json.dumps(db,ensure_ascii=False,indent=2))
 (ROOT/'results/reproduced').mkdir(parents=True,exist_ok=True)
 print(f'Verified {len(records)} source artifacts; unpacked data into build/.')
if __name__=='__main__':main()
