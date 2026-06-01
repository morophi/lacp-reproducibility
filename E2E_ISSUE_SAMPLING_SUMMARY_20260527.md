# E2E Issue Sampling Summary

Date: 2026-05-27

Purpose: E2E smoke/readiness runs exposed several infrastructure and experiment-design risks before formal LACP execution. This note samples each issue, records the observed evidence, identifies the likely cause, and proposes the handling policy for TR/CR/formal runs.

## Executive Judgment

The E2E path is now operational, but the path only became stable after separating three concerns that were initially tangled:

- Runtime readiness: whether A/B/C inference nodes can answer the exact first-turn payload.
- Measurement completeness: whether LMS/CDS/MA artifacts are all available and stored.
- Experimental treatment strength: whether RAG `top_k=5` is realistic under the current BC-250 + Qwen3 + Ollama context/runtime envelope.

The latest validated state is:

- `top_k=2` smoke E2E pass: `e2e_rough_20260527T1032Z`
- `top_k=3` smoke E2E pass: `e2e_rough_topk3_20260527T1043Z`
- `top_k=3` actual first-turn readiness pass: `inference_readiness_20260527T104010Z`
- `metric_complete_rows`: `9/9`
- DB rows: `turn_node_logs=9`, `intervention_logs=9`, `metric_logs=9`
- Current inference temperatures after cooldown: about `47-49 C`

## Issue Samples

### 1. Native Ollama Chat Endpoint Did Not Provide LMS Inputs

Observed evidence:

- Earlier E2E rows used `endpoint_mode=native_chat`.
- `raw_logprobs_len=0`, `clean_logprobs_len=0`.
- Validator reported `metric complete rows 0/9` or `0/15`.
- Conversation export also recorded that `/api/generate` returned response/context fields but not token-level `logprobs` / `top_logprobs`.

Cause:

The native Ollama chat/generate path did not expose token-level candidate distributions needed for LMS. LMS requires per-token top candidate logprobs, not only generated text or context token ids.

Action taken:

- Switched Harness runtime to OpenAI-compatible `/v1/chat/completions`.
- Requested `logprobs=true`, `top_logprobs=5`, `think=false`.
- Added/validated LMS extraction from `choices[0].logprobs.content`.

Policy:

Formal runs should keep OpenAI-compatible chat completions as the LMS-capable endpoint unless a future Ollama/native endpoint is proven to return equivalent token-level candidate data.

### 2. `thinking` Artifact Cleanup Was Needed

Observed evidence:

- Qwen output often began with an empty `<think>\n\n</think>` shell.
- Non-empty reasoning would contaminate response text metrics, but empty shell is a template artifact.

Cause:

The model/template can emit an empty think tag even with `think=false`.

Action taken:

- Empty think shells are stripped.
- Corresponding prefix token positions are excluded from LMS.
- Non-empty thinking content remains a failed TR/quality condition.

Policy:

Keep this gate. It protects LMS/MA/CDS from reasoning-output artifacts while preserving rows in JSONL/DB for audit.

### 3. Synthetic Readiness Probe Missed the Real Payload Problem

Observed evidence:

- Synthetic long probe passed while real smoke first turn failed or became unstable.
- Real first-turn A payload was much larger when RAG + SC were actually assembled.
- Before adjustment, first-turn A prompt reached about `8525` Ollama-side token count / oversized payload behavior.

Cause:

The synthetic probe did not reconstruct the Harness intervention path. It did not load the scenario first turn, apply Run B smoke trigger logic, retrieve RAG chunks, assemble SC policy, and build A/B/C messages exactly as the run would.

Action taken:

- Added actual first-turn dry-run probe to `preflight_inference_readiness.py`.
- It avoids Harness `/turn` and DB writes.
- It loads the scenario first turn, applies Harness config/RAG/SC policy, builds A/B/C messages, and calls inference nodes directly.

Policy:

Readiness for TR/formal should be based on actual first-turn payloads, not only synthetic probes. Synthetic probes may remain an optional diagnostic, but not the primary Go/No-Go gate.

### 4. Synthetic Long Probe Itself Could Destabilize Node B

Observed evidence:

- With synthetic long probe enabled, Node B sometimes passed short and synthetic probes but failed the following actual-first-turn probe.
- Node B error sample:
  `an error was encountered while running the model: signal arrived during cgo execution`
- Failures appeared as `/v1/chat/completions` 500 in Ollama logs.

Cause:

The synthetic 4.2k prompt plus 512-token generation appeared to warm or stress the Vulkan/Ollama runner enough that the subsequent actual-first-turn probe became unreliable. The diagnostic probe became a source of runtime perturbation.

Action taken:

- Removed synthetic long probe from the default readiness path.
- Kept it behind `--include-harness-like-probe` for manual diagnostics only.
- Default gate now uses short sanity + actual first-turn dry-run.

Policy:

Avoid heavy synthetic probes immediately before E2E/formal runs. They can create the very instability they are meant to detect.

### 5. Node B Intermittent 500 Runtime Failures

Observed evidence:

- E2E `e2e_rough_20260527T0930Z`: one Node B row had empty response and raw `error`.
- Readiness failures `inference_readiness_20260527T101802Z` and `102650Z`: Node B returned HTTP 500 on actual-first-turn probe.
- Error message included `signal arrived during cgo execution`.

Cause:

Likely Ollama/Vulkan runner instability under repeated direct logprobs workloads, not a simple RAG context overflow. The failing B prompt was around `2989` chars in `top_k=2` readiness and still failed intermittently.

Action taken:

- Restarted inference2 Ollama to clear runner state.
- Added model unload after readiness probes.
- Avoided repeated heavy probes before E2E.
- Reduced smoke generation budget via `run_modes.smoke.num_predict=256`.

Policy:

Before longer TR/CR runs, treat Node B as the most sensitive node. Use a clean runner, actual-first-turn readiness, cooldown, and no redundant synthetic stress probes.

### 6. CDS Reference Artifact Was Missing

Observed evidence:

- Earlier rows reported:
  `CDS unavailable: reference embedding missing at /home/morophi/harness/reference/reference_embedding.npy`
- Validator showed `metric complete rows 0/9`.

Cause:

The CDS reference vector was not part of the frozen corpus/embedding artifact chain yet. Harness could compute MA/LMS, but CDS was null.

Action taken:

- Built CDS reference from stored Chroma embeddings on the RAG node.
- Placed only read-only artifacts on Harness:
  `/home/morophi/harness/reference/reference_embedding.npy`
  `/home/morophi/harness/reference/reference_embedding.sha256`
  `/home/morophi/harness/reference/reference_embedding_manifest.json`

Policy:

Reference embedding generation must remain an offline RAG/corpus-freeze artifact step. Harness must not become a RAG/corpus factory.

### 7. Reference Embedding Model/Dimension Mismatch Risk

Observed evidence:

- RAG Chroma stored embeddings were 384-dimensional.
- Initial CDS config used `snunlp/KR-SBERT-V40K-klueNLI-augSTS`, which produced 768-dimensional vectors.

Cause:

Using KR-SBERT for response embeddings while averaging stored MiniLM Chroma embeddings would make CDS vector dimensions incompatible.

Action taken:

- Aligned CDS embedding model to `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, matching the stored Chroma embeddings.
- Generated reference by averaging stored vectors, not re-encoding all documents.

Policy:

CDS reference and response embedding model must be dimensionally and semantically paired. The manifest must record collection, count, embedding model, source embedding stream hash, and output hash.

### 8. Harness/RAG Role Boundary Almost Became Blurred

Observed evidence:

- During troubleshooting, there was a tempting path to use Harness packages/cache to generate reference embeddings.
- User correctly flagged that Harness should not take over RAG artifact creation.

Cause:

Operational pressure to make E2E pass can blur architectural roles.

Action taken:

- Stopped the 12,240 chunk re-encoding job.
- Deleted the re-encoding helper.
- Kept only the stored-embedding reference builder as an offline artifact step.
- Harness receives fixed files only.

Policy:

This boundary matters for academic defensibility:

- RAG/corpus node: chunking, embeddings, Chroma, reference artifact generation.
- Harness: orchestration, intervention policy, prompt assembly, metric computation from fixed artifacts, logging.
- Inference nodes: generation only.

### 9. `top_k=5` Is Not Currently a Safe Formal Default

Observed evidence:

- Earlier full top-k path inflated actual payloads enough to exceed stable envelope.
- `top_k=2` smoke pass:
  - A prompt avg/max: `3083 / 3436`
  - B prompt avg/max: `2614 / 2989`
  - metric complete: `9/9`
- `top_k=3` smoke pass:
  - A prompt avg/max: `4167 / 4766`
  - B prompt avg/max: `3757 / 4319`
  - metric complete: `9/9`
  - no empty response, no 500, DB rows `9/9`
- `top_k=3` actual-first-turn readiness:
  - A prompt `4766`
  - B prompt `4319`
  - C prompt `217`

Cause:

The frozen collection still returns chunks around 1200 chars in relevant first-turn retrieval. At `top_k=5`, A/B prompt size plus SC/history growth is likely to cross the practical runtime envelope, even if the nominal context limit is 4096 tokens rather than chars.

Action taken:

- Smoke `rag_top_k` was first lowered to 2 to recover pass.
- Then raised to 3 to test a more realistic middle point.
- `top_k=3` passed the 3-turn smoke path.

Policy:

Formal `top_k=5` should be treated as unsafe until proven otherwise. Current evidence supports evaluating `top_k=3` as the realistic formal candidate, with longer TR validation before CR.

### 10. `num_predict=512` Was Too Heavy for Smoke Evidence

Observed evidence:

- Long generation with logprobs increased latency and Node B instability risk.
- Smoke evidence does not need long answer bodies; it needs complete rows, non-empty text, LMS/CDS/MA, RAG/SC routing, and DB persistence.

Cause:

Generation budget was inherited from formal-like settings, but smoke readiness is a plumbing/evidence gate.

Action taken:

- Added run-mode-specific `num_predict`.
- Smoke uses `num_predict=256`.
- Formal global setting remains separately configurable.

Policy:

Smoke and formal generation budgets should be separated. Smoke can use shorter generation to validate pipeline integrity; formal run budget should be decided after top-k and stability are fixed.

### 11. Validator Initially Failed Because Its Completeness Definition Was Correct but Artifacts Were Missing

Observed evidence:

- Validator blocked on:
  - `response_text empty rows: 1`
  - `timeout_or_500_rows: 1`
  - `metric complete rows 0/9`
- After fixes, validator passed:
  - `metric_complete_rows 9/9`
  - `response_empty_rows 0`
  - `row_count 9`

Cause:

The validator was not the main bug. It exposed real missing CDS and runtime error conditions.

Action taken:

- Fixed runtime and measurement artifacts instead of relaxing validator.

Policy:

Keep validator strict for TR readiness. If run modes differ, document the intended acceptance criteria rather than silently weakening checks.

### 12. DB Path and Async Logging Were Ultimately Healthy

Observed evidence:

- Successful runs showed:
  - `turn_node_logs 9`
  - `intervention_logs 9`
  - `metric_logs 9`
- Harness `/flush` completed during actual run execution.

Cause:

Earlier blocked states were inference/metric-artifact problems, not primarily DB schema or writer failures.

Action taken:

- Kept DB schema check in E2E script.
- Kept explicit log flush after scenario execution.

Policy:

DB logging is acceptable for short E2E/TR readiness under current latency regime, but should remain separately monitored for long CR/CF runs.

### 13. Thermal Behavior Is Manageable but Must Stay in the Protocol

Observed evidence:

- `top_k=2` smoke thermal max:
  - inference1 `79 C`
  - inference2 `73 C`
  - inference3 `71 C`
- `top_k=3` smoke thermal max:
  - inference1 `80 C`
  - inference2 `74 C`
  - inference3 `74 C`
- Later cooldown check:
  - inference1 `47.75 C`
  - inference2 `48.5 C`
  - inference3 `47.125 C`

Cause:

Parallel A/B/C generation produces meaningful heat spikes, especially with logprobs and RAG prompts.

Action taken:

- Added thermal logging during E2E.
- Used cooldown and current-temperature checks before further action.

Policy:

Formal runs need fixed cooldown policy and thermal evidence. Temperature control is an infrastructure control, not an experimental treatment.

### 14. SSH/Sandbox Path Issues Affected Local Tooling

Observed evidence:

- Direct shell `ssh` worked, but Python subprocess inside sandbox sometimes resolved `jump` against a sandbox home and failed.
- `ssh -G jump` showed sandbox user config fallback.

Cause:

Codex sandbox environment and actual user SSH config differ.

Action taken:

- Used escalated shell execution for SSH-dependent readiness/E2E commands.

Policy:

Internal-network E2E commands should be run in the actual user environment, not sandbox-only SSH context.

### 15. Harness Service Restart Target Was Initially Misidentified

Observed evidence:

- Restart via system service failed with unit not found.
- Actual service was `systemctl --user lacp-harness.service`.

Cause:

Harness is a user service, not system service.

Action taken:

- Restarted with `systemctl --user restart lacp-harness.service`.

Policy:

Document service ownership in runbook to avoid false negative operational failures.

## Current Stable Configuration Snapshot

Smoke path:

- `endpoint_mode`: OpenAI-compatible chat completions
- `request_logprobs`: true
- `top_logprobs`: 5
- `think`: false
- `run_modes.smoke.rag_top_k`: 3
- `run_modes.smoke.num_predict`: 256
- CDS reference: present and hash-checked

Important caveat:

- Formal path still needs an explicit top-k decision. The current evidence argues against formal `top_k=5` without further proof.

## Recommended Next Actions

1. Promote `top_k=3` to the leading formal candidate.
2. Run a longer `top_k=3` TR-like smoke, preferably 5 turns with thermal logging and cooldown.
3. Record top-k decision as an experimental-operational constraint, not a post-hoc convenience.
4. Freeze CDS artifact manifest with corpus/chunk/collection metadata before CR.
5. Keep synthetic long probe optional only.
6. Keep actual first-turn dry-run as the mandatory pre-run gate.
7. Before CR, run one clean preflight after restarting inference2 and allowing cooldown.

## Professor Discussion Framing

The strongest framing is not "we fixed bugs until it passed." It is:

The E2E process converted informal system readiness into explicit, auditable experimental controls. Each failure identified a boundary condition: LMS endpoint capability, CDS artifact completeness, RAG context size, inference-node runtime stability, thermal behavior, and DB persistence. The final pass is therefore not merely a successful run; it is evidence that the experiment now has a defined operational envelope.

This is consistent with the broader project framing from the professor-discussion context: the argument should rest on structure, observable behavior, reproducible logs, and system-level evidence rather than conceptual claims alone.
