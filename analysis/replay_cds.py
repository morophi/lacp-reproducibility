"""Optional offline response-embedding replay using a separately supplied model snapshot."""
from pathlib import Path
import argparse,hashlib,json,os,sys
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['TOKENIZERS_PARALLELISM']='false'
R=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--model-path',type=Path,required=True)
args=parser.parse_args();modelpath=args.model_path.resolve()
prior=json.loads((R/'evidence/audit_20260927/cds_remote_replay.json').read_text())
for item in prior['cached_model_files']:
 parts=Path(item['path']).parts
 assert parts[0]=='snapshots'
 file=modelpath/Path(*parts[2:])
 if not file.is_file():raise SystemExit(f'Missing model file: {file}')
 digest=hashlib.sha256()
 with file.open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
 if digest.hexdigest()!=item['sha256']:raise SystemExit(f'Model checksum mismatch: {file}')
import pandas as pd
import torch,sentence_transformers
torch.set_num_threads(1)
model=sentence_transformers.SentenceTransformer(str(modelpath),local_files_only=True,device='cpu')
# Reuse this one verified model instance inside the original metric function.
sentence_transformers.SentenceTransformer=lambda *a,**kw:model
sys.path.insert(0,str(R/'src/harness'))
from metrics import compute_cds,strip_empty_think_tags
def rd(n):return pd.read_csv(R/'build/db/csv'/f'{n}.csv',keep_default_na=False,low_memory=False)
r=rd('experiment_runs');t=rd('turn_node_logs');m=rd('metric_logs')
ids=r[(r.run_mode=='formal')&(r.acceptance_status=='accepted')].id
d=t[t.experiment_run_id.isin(ids)].merge(m[['turn_node_log_id','cds']],left_on='id',right_on='turn_node_log_id',validate='one_to_one')
scores={}
for x in d.drop_duplicates('response_hash').itertuples():
 scores[x.response_hash]=compute_cds(strip_empty_think_tags(x.response_text),str(R/'data/rag/reference/reference_embedding.npy'),str(modelpath),str(R/'data/rag/reference/reference_embedding.sha256'))['cds']
rows=[{'turn_node_log_id':x.id,'stored_cds':float(x.cds),'replayed_cds':scores[x.response_hash],'absolute_error':abs(float(x.cds)-scores[x.response_hash])} for x in d.itertuples()]
out=R/'results/reproduced';out.mkdir(parents=True,exist_ok=True)
pd.DataFrame(rows).to_csv(out/'cds_fresh_response_replay.csv',index=False)
report={'rows':len(rows),'unique_response_embeddings':len(scores),'maximum_absolute_error':max(x['absolute_error'] for x in rows),'matched_at_1e_12':sum(x['absolute_error']<1e-12 for x in rows),'fresh_response_embedding_inference':True}
(out/'cds_fresh_response_replay.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report));assert report['matched_at_1e_12']==7200
