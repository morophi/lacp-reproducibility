"""Fail if reproduced tables or the scientific invariants differ from reference results."""
from pathlib import Path
import importlib.metadata,json,platform
import pandas as pd
R=Path(__file__).resolve().parents[1];O=R/'results/reproduced'
tables=['main_contrasts.csv','trigger_contrasts.csv','cf_contrasts.csv','routing.csv','response_reproducibility.csv','run_mean_dispersion.csv','turn_mean_dispersion.csv']
for name in tables:
 a=pd.read_csv(O/name,keep_default_na=False);b=pd.read_csv(R/'results/reference'/name,keep_default_na=False)
 pd.testing.assert_frame_equal(a,b,check_exact=False,atol=1e-12,rtol=1e-12)
metric=json.loads((O/'metric_replay_summary.json').read_text())
chain=json.loads((O/'execution_chain_summary.json').read_text())
assert all(v==7200 for v in metric['checks'].values())
assert all(v==7200 for v in chain['checks'].values())
assert chain['formal_runs']==80 and chain['log_rows']==7200
assert chain['config_hash_matched_runs']==80
assert chain['trigger_checks']['matches']==900
summary={'status':'PASS','reference_tables_matched':tables,'formal_runs':80,'formal_rows':7200,'run_b_runs':30,'run_b_rows':2700,'metric_replay_all_rows_match':True,'prompt_and_payload_reconstruction_all_rows_match':True,'trigger_decisions_matched':900,'fresh_response_embedding_inference':False,'new_llm_generations':0,'comparison_atol':1e-12,'python':platform.python_version(),'packages':{n:importlib.metadata.version(n) for n in ['numpy','pandas']}}
(O/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary))
