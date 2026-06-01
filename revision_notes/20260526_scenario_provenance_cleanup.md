# Scenario Provenance Cleanup — 2026-05-26

## Decision

Scenario source files belong to the agent/jump node and the project
preservation bundle, not to the Harness runtime node.

Harness must remain the experiment controller:

```text
agent/jump -> utterance source and scenario provenance
harness -> /turn receiver, intervention controller, node caller, metrics/DB writer
```

## Removed Harness Copy

The following misplaced scenario copy was removed from the Harness node active
filesystem:

```text
node = harness
path = /home/morophi/scenario/lacp_30turn_civil_complaint_v1.json
sha256 = 8303dd12a5e488ea546114e074742ed272af928cdc836fa10057aabcf0b79369
size_bytes = 5963
reason = scenario provenance belongs to agent/jump; retaining a Harness copy creates role-boundary and source-file ambiguity
```

No separate Harness quarantine copy was kept because the historical scenario
copy and execution provenance already exist on the agent/jump side, and the
project folder preserves the canonical v2 scenario input.

## Current Agent/JUMP Scenario State

The agent node currently has the v2 scenario in both source JSONL and
agent-executable JSON form:

```text
node = jump / agent
jsonl_path = /home/morophi/agent/scenario/lacp_scenario_base_v2.jsonl
jsonl_sha256 = bbd155a3e87152df770ed175a8914ab30fa0458f6c959b90027843c26bf900ed
json_path = /home/morophi/agent/scenario/lacp_scenario_base_v2.json
json_sha256 = 025884c27aa9bdf041359862433b9d888a8e20c3e2bf61a2d4af3fcda6478979
turn_count = 30
```

The executable JSON contains `turn_no` and `utterance` fields derived from the
v2 JSONL `turn` and `content` fields, so it is compatible with
`runtime_impl/agent/scenario_loader.py`.

## Operational Rule

Future rough/TR/CR runs must pass the agent-side v2 executable JSON path to
`run_scenario.py`. Harness-side scenario paths must not be used as run inputs.

