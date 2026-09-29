from pathlib import Path
import json, hashlib, unicodedata, argparse
import pandas as pd
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Reaggregate archived LACP formal measurements; no model inference or metric re-extraction.')
parser.add_argument('--export',type=Path);parser.add_argument('--output',type=Path)
args=parser.parse_args()
BASE=args.export or ROOT/'build/db'
OUT=args.output or ROOT/'results/reproduced'
OUT.mkdir(parents=True,exist_ok=True)
def read(n): return pd.read_csv(BASE/'csv'/f'{n}.csv',keep_default_na=False,low_memory=False)
def flag(s): return s.astype(str).str.lower().isin(['true','t','1'])
def js(s): return json.loads(s) if isinstance(s,str) and s else {}
r=read('experiment_runs'); t=read('turn_node_logs'); m=read('metric_logs'); p=read('payload_audit_logs'); iv=read('intervention_logs'); rag=read('rag_retrieval_logs')
metrics=['lms_value','cds','ma_assert','srr','sci']
d=t[['id','experiment_run_id','turn_no','node','response_text','response_hash','metric_status']].merge(r[['id','run_id','stage','run_mode','acceptance_status']],left_on='experiment_run_id',right_on='id',suffixes=('','_run'),validate='many_to_one').merge(m[['turn_node_log_id']+metrics+['ma_epist','ma_hedge','sent_count','metrics_json','theta_entropy']],left_on='id',right_on='turn_node_log_id',validate='one_to_one').merge(p[['turn_node_log_id','rag_injected','sc_policy_applied','history_window_turns_configured','history_turns_used','message_count','prompt_hash','payload_hash','retrieved_chunk_ids_hash']],on='turn_node_log_id',validate='one_to_one')
d=d[(d.acceptance_status=='accepted')&(d.run_mode=='formal')].copy()
for c in metrics+['ma_epist','ma_hedge','sent_count','theta_entropy']: d[c]=pd.to_numeric(d[c],errors='coerce')
for c in ['rag_injected','sc_policy_applied']:d[c]=flag(d[c])
assert not d.duplicated(['experiment_run_id','turn_no','node']).any()
assert d[metrics].notna().all().all()
assert set(d.node)==set('ABC')
b=d[d.stage=='run_b'].copy(); cr2=d[d.stage=='cr2'].copy(); cf=d[d.stage.str.startswith('cf_')].copy()
assert len(b)==2700 and b.experiment_run_id.nunique()==30
assert len(cf)==3150 and cf.experiment_run_id.nunique()==35
assert len(cr2)==450 and cr2.experiment_run_id.nunique()==5
assert (d.groupby(['experiment_run_id','node']).size()==30).all()

def pairs(frame,x,y):
    wide=frame.pivot(index=['experiment_run_id','turn_no'],columns='node',values=metrics)
    out=pd.DataFrame({c:wide[(c,x)]-wide[(c,y)] for c in metrics})
    out['cds']*=-1
    return out.reset_index()
ab=pairs(b,'A','B');bc=pairs(b,'B','C');ac=pairs(b,'A','C')
trigger=[8,20,25]
groups={'A-B trigger':ab[ab.turn_no.isin(trigger)],'A-B non-trigger':ab[~ab.turn_no.isin(trigger)],'B-C all':bc,'A-C all':ac,'A-B pre 1-7':ab[ab.turn_no<8],'A-B later non-trigger':ab[(ab.turn_no>8)&~ab.turn_no.isin(trigger)]}
contrast=[];runstats=[];turnstats=[]
for name,g in groups.items():
    contrast.append({'contrast':name,'paired_rows':len(g),'distinct_turns':g.turn_no.nunique(),**g[metrics].mean().to_dict()})
    for c in metrics:
        v=g.groupby('experiment_run_id')[c].mean();u=g.groupby('turn_no')[c].mean()
        runstats.append({'contrast':name,'metric':c,'runs':len(v),'median':v.median(),'min':v.min(),'max':v.max(),'sd':v.std(ddof=1)})
        turnstats.append({'contrast':name,'metric':c,'turns':len(u),'median':u.median(),'min':u.min(),'max':u.max(),'positive_turns':int((u>1e-10).sum()),'negative_turns':int((u< -1e-10).sum()),'zero_turns':int((u.abs()<=1e-10).sum())})
pd.DataFrame(contrast).to_csv(OUT/'main_contrasts.csv',index=False)
pd.DataFrame(runstats).to_csv(OUT/'run_mean_dispersion.csv',index=False)
pd.DataFrame(turnstats).to_csv(OUT/'turn_mean_dispersion.csv',index=False)
ab[ab.turn_no.isin(trigger)].groupby('turn_no')[metrics].mean().to_csv(OUT/'trigger_contrasts.csv')
rows=[]
for stage,g in cf.groupby('stage'):
    for x,y in [('A','B'),('B','C')]:
        z=pairs(g,x,y);rows.append({'condition':stage,'contrast':x+'-'+y,'runs':g.experiment_run_id.nunique(),'pairs':len(z),**z[metrics].mean().to_dict()})
pd.DataFrame(rows).to_csv(OUT/'cf_contrasts.csv',index=False)
routing=d.groupby(['stage','node']).agg(rows=('id','size'),rag_rows=('rag_injected','sum'),rbc_rows=('sc_policy_applied','sum')).reset_index()
routing['rag_turns']=routing.apply(lambda z:','.join(map(str,sorted(d[(d.stage==z.stage)&(d.node==z.node)&d.rag_injected].turn_no.unique()))),axis=1)
routing['rbc_turns']=routing.apply(lambda z:','.join(map(str,sorted(d[(d.stage==z.stage)&(d.node==z.node)&d.sc_policy_applied].turn_no.unique()))),axis=1)
routing.to_csv(OUT/'routing.csv',index=False)

hashstats=[]
for (turn,node),g in b.groupby(['turn_no','node']):
    h=g.response_hash.value_counts();norm=g.response_text.map(lambda x:' '.join(unicodedata.normalize('NFC',x).split())).value_counts()
    hashstats.append({'turn':int(turn),'node':node,'runs':len(g),'distinct_response_hashes':len(h),'modal_count':int(h.iloc[0]),'pairwise_hash_agreement':float((h*(h-1)).sum()/(len(g)*(len(g)-1))),'normalized_distinct':len(norm)})
hs=pd.DataFrame(hashstats);hs.to_csv(OUT/'response_reproducibility.csv',index=False)
assert (hs.distinct_response_hashes==hs.normalized_distinct).all()

audit={};lms_errors=[];ma_errors=[];components=[]
for row in d.itertuples():
    st=js(row.metric_status); mj=js(row.metrics_json)
    margins=st.get('lms_selected_margins',[])
    if margins:lms_errors.append(abs(np.mean(margins)-row.lms_value))
    if 'unclassified_count' in mj:ma_errors.append(abs((1-row.ma_assert-row.ma_epist-row.ma_hedge)*row.sent_count-mj['unclassified_count']))
    comps=st.get('sci_components',{})
    components.append({'id':row.id,'stage':row.stage,'turn':row.turn_no,'node':row.node,'srr':row.srr,'sci':row.sci,'sent_count':row.sent_count,'boundary_count':st.get('srr_boundary_count'),'final_count':st.get('srr_final_count'),**comps})
co=pd.DataFrame(components);co.to_csv(OUT/'metric_component_audit.csv',index=False)
audit.update({'formal_rows':len(d),'run_b_rows':len(b),'cf_rows':len(cf),'formal_cr2_rows':len(cr2),'lms_aggregation_checked_rows':len(lms_errors),'lms_mean_max_absolute_error':max(lms_errors),'ma_denominator_checked_rows':len(ma_errors),'ma_denominator_max_absolute_error':max(ma_errors),'reproducibility':{'cells':len(hs),'single_hash_cells':int((hs.distinct_response_hashes==1).sum()),'max_distinct_hashes':int(hs.distinct_response_hashes.max()),'modal_matches':int(hs.modal_count.sum()),'total_responses':len(b),'mean_pairwise_agreement':float(hs.pairwise_hash_agreement.mean())}})
snaps=iv[iv.turn_node_log_id.isin(pd.concat([b,cf]).id)].threshold_snapshot.value_counts()
audit['frozen_threshold_snapshots']=[{'rows':int(n),'snapshot':js(s)} for s,n in snaps.items()]
audit['history']=b.groupby(['history_window_turns_configured','history_turns_used','message_count']).size().reset_index(name='rows').to_dict('records')
audit['formal_run_ids']=d.groupby('stage').run_id.unique().apply(list).to_dict()

cal=[]
ordered=sorted(cr2.experiment_run_id.unique())
for n in [3,5]:
    z=cr2[cr2.experiment_run_id.isin(ordered[:n])]
    for c in ['lms_value','cds','ma_assert']:
        a=pairs(z,'A','C')[c].abs();q=pairs(z,'B','C')[c].abs()
        cal.append({'runs':n,'metric':c,'A-C_q95':a.quantile(.95),'B-C_q95':q.quantile(.95),'pooled_q95':pd.concat([a,q]).quantile(.95),'pooled_rows':len(a)+len(q)})
    ents=[v for st in z[z.node=='C'].metric_status.map(js) for v in st.get('lms_token_entropies',[])]
    audit[f'cr2_{n}_node_c_entropy']={'tokens':len(ents),'q90':float(np.quantile(ents,.9)),'q95':float(np.quantile(ents,.95)),'q75':float(np.quantile(ents,.75))}
pd.DataFrame(cal).to_csv(OUT/'cr2_threshold_reconstruction.csv',index=False)
run_cal=[]
for run,z in cr2.groupby('experiment_run_id'):
    for c in ['lms_value','cds','ma_assert']:
        a=pairs(z,'A','C')[c].abs();q=pairs(z,'B','C')[c].abs()
        run_cal.append({'run_id':int(run),'metric':c,'pooled_q95':pd.concat([a,q]).quantile(.95)})
pd.DataFrame(run_cal).to_csv(OUT/'cr2_run_level_quantiles.csv',index=False)
audit['response_hashes_recomputed_matches']=int(sum(hashlib.sha256(s.encode()).hexdigest()==h for s,h in zip(b.response_text,b.response_hash)))
audit['source_checksums']={'provenance/artifacts.json':hashlib.sha256((ROOT/'provenance/artifacts.json').read_bytes()).hexdigest()}

matches=[]
for label,g in [('pre',b[b.turn_no<8]),('later',b[b.turn_no>=8])]:
    w=g.pivot(index=['experiment_run_id','turn_no'],columns='node',values=['prompt_hash','payload_hash','retrieved_chunk_ids_hash'])
    matches.append({'subset':label,'pairs':len(w),**{f'{col}_A_B_matches':int((w[(col,'A')]==w[(col,'B')]).sum()) for col in ['prompt_hash','payload_hash','retrieved_chunk_ids_hash']}})
audit['ab_input_hash_matches']=matches
audit['run_b_runtime']={col:t[t.id.isin(b.id)][col].value_counts(dropna=False).to_dict() for col in ['model_name','model_digest','temperature','seed','endpoint_mode','thinking_content_present']}
audit['run_b_rag']={col:rag[rag.turn_node_log_id.isin(b.id)][col].value_counts(dropna=False).to_dict() for col in ['top_k','returned_count','retrieval_method']}
audit['srr_boundary_over_sentence_max_error']=float((co.srr-co.boundary_count/co.sent_count).abs().max())
audit['srr_boundary_over_sum_max_error']=float((co.srr-co.boundary_count/(co.boundary_count+co.final_count)).abs().max())
(OUT/'audit_summary.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2,default=lambda x:x.item() if hasattr(x,'item') else str(x)))
b.groupby(['turn_no','node'])[metrics].mean().to_csv(OUT/'node_turn_profiles.csv')
ex=b[b.turn_no==25].merge(co[['id','caution_or_boundary','evidence_or_condition','next_step','verification_route']],on='id')
ex.groupby(['node','response_text']+metrics+['caution_or_boundary','evidence_or_condition','next_step','verification_route'],dropna=False).size().reset_index(name='frequency').to_csv(OUT/'turn25_responses_and_components.csv',index=False)

integrity=[]
for item in json.loads((BASE/'manifest.json').read_text())['relations']:
    f=BASE/item['csv'];integrity.append({'relation':item['name'],'rows':len(pd.read_csv(f,low_memory=False)),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'hash_matches':hashlib.sha256(f.read_bytes()).hexdigest()==item['sha256']})
assert all(x['hash_matches'] for x in integrity)
assert all(x['rows']==item['row_count'] for x,item in zip(integrity,json.loads((BASE/'manifest.json').read_text())['relations']))
(OUT/'export_integrity.json').write_text(json.dumps(integrity,indent=2))
print(json.dumps(audit,ensure_ascii=False,indent=2,default=str))
print(pd.DataFrame(contrast).to_string(index=False));print(pd.DataFrame(cal).to_string(index=False))
