# LACP Harness Runtime Policy

## Purpose

This file records the runtime policy that links quality gating, trigger
eligibility, history handling, and DB evidence preservation. The goal is to
avoid treating every exclusion as the same kind of exclusion.

## Eligibility Separation Policy

LACP Harness manages three eligibility concepts separately.

```text
analysis_eligible
  Whether this node-turn row can enter causal/statistical result analysis.

exclude_from_causal_trigger
  Whether this node-turn row is blocked from influencing later intervention
  timing through TriggerController.

history_eligible
  Whether this node-turn response can be appended to the node's future
  conversation history.
```

`analysis_eligible=false` does not automatically mean future conversation
history exclusion. A response may be unsuitable for causal analysis while still
being a meaningful conversational exchange.

## History Eligibility

Hard context failures are excluded from future node history while still being
stored in JSONL and MariaDB.

Current hard history exclusion reasons:

```text
infrastructure_invalid
empty_response
thinking_content_present
truncation_risk, in formal mode
language_contamination
intervention_contamination
```

Policy-anchor failure alone is not automatically a history exclusion. It is
analysis/trigger-ineligible, but the response can remain history-eligible when
it is otherwise a coherent conversational response.

## Trigger Eligibility

Trigger eligibility is evaluated at two levels.

Row-level exclusion:

```text
exclude_from_causal_trigger=true
analysis_eligible=false
```

When either row-level condition is present, no metric from that row is used for
later intervention timing.

Metric-level eligibility:

```text
lms_trigger_eligible
cds_trigger_eligible
ma_trigger_eligible
overall_trigger_eligible=policy_dependent
```

Missing logprobs disable LMS/LMS-delta trigger evidence only. They do not
automatically disable CDS or MA trigger evidence.

## Missing Logprobs Execution Policy

Missing logprobs are not expected under the normal formal measurement path
after the LMS / Logprob Preflight Run passes.

Formal measurement uses:

```text
run_mode=formal
endpoint_mode=openai_chat_completions
request_logprobs=true
```

Under that path, the expected missing-logprobs probability is low. It is still
kept as an explicit execution policy because its impact is high when it occurs:

```text
missing logprobs
  -> LMS unavailable
  -> LMS_delta unavailable
  -> LMS-based trigger evidence invalid for that node-turn
```

This does not automatically invalidate text or embedding evidence:

```text
MA trigger evidence
  Does not require logprobs.

CDS trigger evidence
  Requires response embedding and reference embedding, not logprobs.
```

Execution interpretation by phase:

```text
Rough / Smoke
  Missing logprobs can occur because these phases are path-readiness checks and
  may use native endpoints. They are not causal evidence phases.

LMS / Logprob Preflight
  A/B/C formal endpoints should show token-level logprob availability. Failure
  here is a No-Go for formal LMS-based measurement.

CR / CR2 / Run B / CF
  Missing logprobs should be rare after preflight. If it occurs, the row remains
  stored, LMS/LMS_delta evidence for that node-turn is invalid, and repeated
  occurrences should be treated as endpoint or run-level readiness failure.
```

## Evidence Preservation

Harness stores quality failures as observations.

```text
Node response
  -> quality gate
  -> metric calculation
  -> JSONL fallback
  -> MariaDB upsert
```

The logger writes JSONL before MariaDB so DB outages do not erase runtime
evidence. MariaDB rows then record analysis, trigger, and history eligibility
fields explicitly for later audits.

## Execute Compatibility Policy

The runtime execute order is unchanged:

```text
scenario JSON
  -> agent
  -> Harness /turn
  -> trigger decision
  -> RAG/SC plan
  -> prompt assembly
  -> A/B/C inference
  -> response cleaning
  -> quality gate
  -> metrics
  -> history update
  -> JSONL
  -> MariaDB
```

The policy update only refines downstream use decisions at these execute
points:

```text
quality gate
metrics / trigger eligibility
history update
```

The execution philosophy is:

```text
storage
  Preserve as much runtime evidence as possible.

analysis
  Select rows strictly by analysis eligibility.

trigger
  Block contaminated rows and unavailable metric families from intervention
  timing.

history
  Exclude only hard context failures from future prompt context.
```

## Formal failed_TR Handling

Formal `failed_TR` no longer stops the turn before evidence persistence.

```text
failed_TR occurs
  -> row preserved in JSONL and MariaDB
  -> analysis_eligible=false
  -> exclude_from_causal_trigger=true
  -> history_eligible=false
```

This changes formal failed_TR behavior from immediate interruption to preserved
ineligible evidence. Run-level Go/No-Go must therefore be decided from a later
quality summary rather than from pre-logging exceptions.

## Deployment Preconditions

The dblog schema must match the runtime logger before MariaDB-backed execution.
Apply this migration on the dblog node before running this Harness version:

```text
dblog_schema/20260525_add_eligibility_separation_fields.sql
```

Without this migration, JSONL fallback still records the full row, but MariaDB
insert/upsert will fail because the new eligibility columns are absent.

## Run Mode Interpretation

```text
smoke
  Path readiness and generation-quality readiness evidence. Not causal
  measurement evidence.

formal
  Measurement path. Hard failures remain stored but are excluded from the
  relevant downstream path: analysis, trigger, history, or a combination.
```

## Experiment Phase Interpretation

```text
Rough Test Run
  Local or remote path sanity before formal readiness claims.

Smoke Test Run
  Harness-to-node, RAG path, and DB writer readiness.

TR Preflight Run
  Thinking-response control, prompt path, response extraction, and DB evidence
  verification.

LMS / Logprob Preflight Run
  Formal endpoint and token-level logprob availability verification.

CR
  Cross-node runtime variance measurement with intervention minimized.

CR2
  Natural metric distribution and theta calibration basis.

Run B
  Primary intervention-effect measurement.

CF-A through CF-F
  Counterfactual and reverse-causality checks using predeclared intervention
  schedules.
```
