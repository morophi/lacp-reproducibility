# LACP Results Readiness Checklist Addendum Rev2

**Purpose**: This addendum supplements `lacp_node_checklist_v8.md` by focusing
on whether the experiment is ready to produce defensible results for the
manuscript. Rev2 adds an explicit threshold-estimation and freeze check for
`theta_entropy`, `theta_LMS`, `theta_CDS`, and `theta_MA`.

**Scope**: It does not replace the infrastructure checklist. Use it after node
setup, service setup, and scenario deployment are complete.

---

## 1. Experiment Execution Order

The experiment must validate corpus quality before any cross-node comparison.
The Pure RAG Ingest Test Run uses no LLM inference nodes and exists only to
verify the corpus before Node A/B/C comparison.

```text
[ ] Required order is fixed
    Dry Run
    -> Pure RAG Ingest Test Run
    -> Retrieval Coherence Test
    -> CR
    -> CR2
    -> threshold estimation and freeze
    -> SCI validation
    -> Run B
    -> CF Runs

[ ] CR entry is blocked until Pure RAG Ingest Test Run and Retrieval Coherence
    Test pass

[ ] Run B entry is blocked until theta_config.json is frozen from CR2

[ ] RAG corpus defects are resolved before CR, Run B, or CF outputs can be
    interpreted
```

---

## 2. Manuscript-Checklist Consistency

```text
[ ] CR sample size is unified across manuscript and checklist
    Final value: N = ___________
    Manuscript locations checked: Section 3.3, Table 2, Section 6

[ ] CR and CR2 purposes are clearly separated
    CR  = cross-node hardware/runtime variance
    CR2 = natural metric distribution and threshold calibration

[ ] Run B status is clearly labeled
    [ ] Pilot only
    [ ] Main run
    Final Run B N: ___________

[ ] CF-A through CF-F repetition count is fixed before execution
    Final CF N per condition: ___________

[ ] Bonferroni correction and alpha level are fixed before analysis
    alpha before correction: ___________
    corrected alpha: ___________
```

---

## 3. Node Role and Treatment Integrity

The paper's causal claim depends on Node A, Node B, and Node C receiving
identical utterances while differing only in intervention condition.

```text
[ ] Node A route verified
    Condition: RAG + SC-Protocol
    RAG enabled: yes
    SC trigger monitoring: yes

[ ] Node B route verified
    Condition: RAG only
    RAG enabled: yes
    SC trigger monitoring: no, or logged separately without intervention effect

[ ] Node C route verified
    Condition: baseline concurrent control
    RAG enabled: no
    SC trigger monitoring: no

[ ] Identical prompt payload is logged for A/B/C at every turn
    Verification query:
    SELECT run_id, turn, COUNT(DISTINCT prompt) FROM turn_logs GROUP BY run_id, turn;

[ ] RAG injection flags are condition-consistent
    Node A: rag_injected follows SC or forced CF condition
    Node B: rag_injected follows RAG-only condition
    Node C: rag_injected must always be 0

[ ] SC trigger flags are condition-consistent
    Node A: sc_triggered may be 0 or 1
    Node B: sc_triggered must not alter prompt/context
    Node C: sc_triggered must remain 0 or NULL

[ ] Any deviation is logged in run note field before analysis
```

---

## 4. Simultaneity and Runtime Variance

```text
[ ] asyncio.gather dispatch delta is measured and recorded
    Required target: delta < 1 ms
    Observed value: ___________ ms

[ ] Per-turn elapsed_ms is stored for all A/B/C responses

[ ] CR confirms residual cross-node variance under identical conditions
    CR run_id: ___________
    variance summary file: ___________

[ ] No large file transfer occurred during measured runs

[ ] GPU backend status was checked immediately before each run
    ollama ps result: ___________

[ ] First warm-up query was executed and discarded before measured responses
```

---

## 5. LMS and Entropy Threshold Readiness

```text
[ ] Ollama logprobs/top-logprobs extraction format is recorded
    Ollama version: ___________
    logprob field name: ___________
    top-k available: yes / no

[ ] Raw token-level logit/logprob data is stored or exportable
    Storage location/table: ___________

[ ] z1 - z2 can be computed for every included token

[ ] token_count after filtering is stored per turn

[ ] theta_entropy is computed only from CR2 RAG-off natural responses
    CR2 run_id used: ___________
    percentile: 70th
    theta_entropy value: ___________

[ ] theta_entropy is recorded as an LMS token-eligibility filter, not as an
    intervention-effect threshold

[ ] theta_entropy is frozen before Run B and CF runs

[ ] POS-filter robustness analysis is prepared
    Excluded categories: particles, endings, punctuation, EOS
    Analyzer/version file: morpheme_version.txt
```

---

## 6. Unified Trigger Threshold Estimation and Freeze Check

```text
[ ] theta_LMS, theta_CDS, and theta_MA are estimated from CR2 using Node
    C-relative intervention-oriented differential scores

[ ] D_LMS^X(t) = LMS_X(t) - LMS_C(t) is used for LMS threshold estimation

[ ] D_CDS^X(t) = CDS_C(t) - CDS_X(t) is used for CDS threshold estimation

[ ] D_MA^X(t) = MA_assert_X(t) - MA_assert_C(t) is used for MA threshold
    estimation

[ ] theta_LMS, theta_CDS, and theta_MA are computed as empirical 95th
    percentiles of |D_k^X(t)| under the CR2 RAG-off condition

[ ] Run B and CF threshold exceedance logic uses intervention-oriented direction:
    D_LMS > theta_LMS
    D_CDS > theta_CDS
    D_MA  > theta_MA

[ ] theta_config.json contains all required fields:
    theta_lms
    theta_cds
    theta_ma
    theta_entropy
    cr2_run_id
    percentile_rule
    direction_convention
    node_config_hash
    sc_policy_hash
    corpus_hash
    code_git_sha
    created_at
    locked

[ ] theta_config.json is locked before Run B

[ ] Run B and CF runs load theta values from theta_config.json and do not
    re-estimate thresholds

[ ] Any missing LMS/logprobs rows are excluded from theta_LMS estimation and
    recorded as metric availability failures

[ ] Threshold table is exported and archived before Run B execution
    Output file: ___________

[ ] CR2 threshold-generation script hash is recorded
    Script path: ___________
    Script SHA-256 or Git SHA: ___________
```

---

## 7. MA Readiness

```text
[ ] Sentence splitter version or rule set is fixed
    Rule/version: ___________

[ ] Korean sentence-final ending dictionary is version controlled
    Dictionary Git SHA: ___________

[ ] Morphological analyzer version is fixed
    morpheme_version.txt path: ___________

[ ] Priority rule is implemented
    Hedging > Epistemic > Assertive

[ ] MA output stores all required fields
    ma_assert, ma_epist, ma_hedge, sent_count

[ ] MA threshold interpretation uses D_MA, not raw MA_assert

[ ] Manual spot check completed on at least 30 sentences
    Spot-check file: ___________
```

---

## 8. CDS Readiness

```text
[ ] Reference policy objective embedding is generated from the RAG corpus
    Corpus snapshot path: ___________
    Embedding model: ___________
    Embedding model version/hash: ___________

[ ] CDS formula is fixed
    cosine distance = 1 - cosine similarity

[ ] Same embedding model is used for reference and response embeddings

[ ] RAG corpus version is frozen before CR, CR2, Run B, and CF runs
    Corpus Git SHA or archive hash: ___________
    Corpus hash file: corpus_hash.txt
    Embedding hash file: embedding_hash.txt

[ ] CDS values are stored per run_id, turn, node

[ ] CDS threshold interpretation uses D_CDS = CDS_C - CDS_X, not raw CDS

[ ] Immediate post-injection CDS decrease test is implemented
    Test script: ___________
```

---

## 9. SRR Readiness

```text
[ ] Previous-turn window size is fixed
    Required by manuscript: preceding 3 turns

[ ] Self-reference threshold is fixed
    cosine similarity threshold: 0.85

[ ] Simple repetition exclusion is implemented
    N-gram size: 3
    overlap threshold: 0.4

[ ] SRR calculation handles turns 1-3 consistently
    Method: ___________

[ ] SRR output is stored per run_id, turn, node
```

---

## 10. SCI Readiness

```text
[ ] Claim-evidence-conclusion annotation guideline is written
    Guideline path: ___________

[ ] Minimum 30 sentence pre-validity sample is prepared
    Sample file: ___________

[ ] Two independent annotators completed labels
    Annotator A file: ___________
    Annotator B file: ___________

[ ] Cohen's kappa is calculated
    kappa value: ___________

[ ] SCI inclusion rule is applied
    [ ] kappa >= 0.6, use SCI
    [ ] kappa < 0.6, replace SCI with sentence-type proportion measure

[ ] Decision is recorded before Run B analysis
```

---

## 11. Counterfactual Condition Readiness

```text
[ ] CF-A content substitution document pair is frozen
    Document C hash: ___________
    Document D hash: ___________

[ ] CF-B empty retrieval behavior is verified
    Empty result produces no hidden fallback context: yes / no

[ ] CF-C opposing/previous-version policy document is frozen
    Document hash: ___________
    Date identifiers removed: yes / no

[ ] CF-D forced turns are fixed
    Required by manuscript: turns 5, 15, 25

[ ] CF-E confirms model weights are fixed and only external context varies
    qwen3 digest: ___________

[ ] CF-F random intervention seed is fixed before execution
    seed: ___________
    injection turns: ___________

[ ] CF-F trigger-ineligible condition is verified
    Source baseline: CR2 thresholds
    Verification file: ___________

[ ] CF-F turns are not edited after seeing experimental responses
```

---

## 12. Results Export Readiness

These outputs are required to fill the manuscript's Results section without
reconstructing evidence manually.

```text
[ ] Table: CR cross-node variance summary
    Output file: ___________

[ ] Table: CR2 natural metric distribution and thresholds
    Output file: ___________

[ ] Table: Run B Node A/B/C metric summary
    Includes LMS, MA, CDS, SRR, SCI or replacement metric
    Output file: ___________

[ ] Figure: LMS_delta_A and LMS_delta_B over turns
    Output file: ___________

[ ] Figure: D_LMS, D_CDS, and D_MA over turns with threshold lines
    Output file: ___________

[ ] Figure: CDS over turns with injection markers
    Output file: ___________

[ ] Figure/Table: Node A > Node B > Node C ordering test
    Output file: ___________

[ ] Table: CF-A through CF-F causal contribution summary
    Output file: ___________

[ ] Table: CF-F reverse-causality refutation test
    Output file: ___________

[ ] Effect size estimates are exported
    Cohen's d / confidence intervals file: ___________

[ ] Power analysis based on Run B pilot is exported
    Required main N: ___________
    Output file: ___________

[ ] All generated plots include run_id and timestamp in metadata or filename
```

---

## 13. Database Sanity Queries Before Analysis

```sql
-- Node C should never receive RAG.
SELECT run_id, COUNT(*) AS node_c_rag_count
FROM turn_logs
WHERE node = 'C' AND rag_injected = 1
GROUP BY run_id;

-- A/B/C should all exist for each turn.
SELECT run_id, turn, COUNT(DISTINCT node) AS node_count
FROM turn_logs
GROUP BY run_id, turn
HAVING node_count <> 3;

-- Metric rows should match turn logs.
SELECT t.run_id, t.turn, t.node
FROM turn_logs t
LEFT JOIN metric_logs m
  ON t.run_id = m.run_id AND t.turn = m.turn AND t.node = m.node
WHERE m.id IS NULL;

-- Confirm theta entropy is fixed within each run after CR2.
SELECT run_id, COUNT(DISTINCT theta_entropy) AS theta_count
FROM metric_logs
GROUP BY run_id
HAVING theta_count <> 1;

-- Confirm Node C has no intervention-oriented trigger source role.
SELECT run_id, COUNT(*) AS node_c_trigger_source_count
FROM turn_logs
WHERE node = 'C' AND sc_triggered = 1
GROUP BY run_id;
```

---

## 14. Final Go / No-Go

```text
[ ] Experiment execution order includes Pure RAG Ingest Test Run and Retrieval
    Coherence Test before CR
[ ] Pure RAG Ingest Test Run passes all corpus quality gates
[ ] Retrieval Coherence Test passes all retrieval meaning-preservation gates
[ ] Manuscript run numbers are internally consistent
[ ] Node role routing is verified
[ ] RAG and SC flags are condition-consistent
[ ] LMS/logprobs pipeline is working
[ ] theta_entropy is fixed from CR2 only
[ ] theta_LMS, theta_CDS, and theta_MA are fixed from CR2 Node C-relative
    oriented differentials
[ ] theta_config.json is locked and archived before Run B
[ ] MA dictionary and analyzer versions are frozen
[ ] CDS reference embedding is frozen
[ ] SRR rules are implemented exactly as written
[ ] SCI validity decision is made before analysis
[ ] CF-F trigger-ineligible verification is complete
[ ] DB sanity queries return no blocking anomalies
[ ] Results export scripts produce all manuscript-ready tables and figures
```

**Decision**:

```text
[ ] GO
[ ] NO-GO

Reviewer: ___________
Date: ___________
Notes:
____________________________________________________________
____________________________________________________________
```

