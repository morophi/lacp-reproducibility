"""Rebuild the frozen CDS reference; verify prior response-level CDS replay evidence."""
from pathlib import Path
import hashlib,io,json
import numpy as np
import pandas as pd
R=Path(__file__).resolve().parents[1];O=R/'results/reproduced'
a=np.load(R/'data/rag/embeddings.npy',allow_pickle=False)
m=json.loads((R/'data/rag/reference/reference_embedding_manifest.json').read_text())
assert a.shape==(12240,384) and a.dtype==np.float32
stream=hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
assert stream==m['source_embedding_stream_sha256']
total=None
for offset in range(0,len(a),512):
 batch=a[offset:offset+512].sum(axis=0,dtype=np.float64)
 total=batch if total is None else total+batch
ref=(total/len(a)).astype(np.float32);ref=ref/float(np.linalg.norm(ref))
stored=np.load(R/'data/rag/reference/reference_embedding.npy',allow_pickle=False)
assert np.array_equal(ref,stored)
b=io.BytesIO();np.save(b,ref);digest=hashlib.sha256(b.getvalue()).hexdigest()
assert digest==m['output_sha256']
(O/'reference_embedding.npy').write_bytes(b.getvalue())
# These scores were recalculated using the cached embedding model on 2026-09-27.
# This default check joins archived scores; it does not run the embedding model again.
arch=json.loads((R/'evidence/audit_20260927/cds_remote_replay.json').read_text())
scores={x['response_hash']:x['cds'] for x in arch['rows']}
def rd(name):return pd.read_csv(R/'build/db/csv'/f'{name}.csv',keep_default_na=False,low_memory=False)
r=rd('experiment_runs');t=rd('turn_node_logs');v=rd('metric_logs')
ids=r[(r.run_mode=='formal')&(r.acceptance_status=='accepted')].id
d=t[t.experiment_run_id.isin(ids)].merge(v[['turn_node_log_id','cds']],left_on='id',right_on='turn_node_log_id',validate='one_to_one')
errors=[abs(float(x.cds)-scores[x.response_hash]) for x in d.itertuples()]
assert len(errors)==7200 and max(errors)<1e-12
report={'reference_shape':list(a.shape),'source_embedding_stream_sha256':stream,'rebuilt_reference_sha256':digest,'reference_array_equal':True,'archived_cds_rows_matched':len(errors),'max_cds_absolute_error':max(errors),'fresh_response_embedding_inference':False,'archived_cds_replay_date':'2026-09-27'}
(O/'reference_and_cds_evidence.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
