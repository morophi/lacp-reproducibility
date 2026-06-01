# LACP Paper Rev9 Threshold Revision Draft

Purpose: close the threshold-definition gap in rev8.1 by separating the LMS
token-eligibility threshold from trigger/effect thresholds, and by defining all
trigger thresholds on Node C-relative intervention-oriented differential scores.

## 1. Revision Summary

Rev8.1 already defines `theta_entropy` as an LMS-internal entropy filter derived
from the CR2 natural RAG-off token-entropy distribution. That definition is kept.

The trigger thresholds `theta_LMS`, `theta_CDS`, and `theta_MA` are redefined as
CR2-derived thresholds over Node C-relative intervention-oriented differential
scores. This aligns threshold estimation with the paper's causal contrast:
Node A/B responses are interpreted relative to the concurrent no-intervention
Node C baseline, not as raw metric values.

## 2. New Section To Insert

Suggested location: insert before the current Section 4.6
`Five-Dimensional Measurement Integration`. The existing Section 4.6 should
be renumbered to 4.7.

Suggested section title:

```text
4.6 Threshold Estimation and Freezing
```

Suggested manuscript text:

```text
Two classes of thresholds are distinguished in this study. The entropy
threshold theta_entropy is used only as an internal token-eligibility filter
for LMS computation, whereas theta_LMS, theta_CDS, and theta_MA are used as
trigger and intervention-effect thresholds for detecting metric shifts beyond
natural variation.

The entropy threshold theta_entropy is estimated independently from the CR2
natural RAG-off token-entropy distribution as the pre-registered 70th
percentile. This threshold is not interpreted as an intervention-effect
threshold; it only determines which tokens are eligible for LMS computation.

For causal trigger and intervention-effect interpretation, thresholds are
estimated using within-turn differential scores relative to Node C, the
concurrent no-intervention baseline. This choice follows the experimental
contrast of the LACP design: RAG effects are not defined as absolute metric
increases, but as deviations from the matched concurrent baseline under fixed
user utterances, fixed model weights, deterministic decoding, and synchronized
turn-level execution.

For each turn t and node X in {A, B}, the intervention-oriented differential
scores are defined as follows:

D_LMS^X(t) = LMS_X(t) - LMS_C(t)

D_CDS^X(t) = CDS_C(t) - CDS_X(t)

D_MA^X(t) = MA_assert_X(t) - MA_assert_C(t)

The sign convention is selected so that larger values consistently indicate
stronger intervention-oriented movement: increased LMS commitment relative to
Node C, decreased CDS distance toward the fixed policy reference relative to
Node C, and increased assertive modality relative to Node C.

During CR2, thresholds are estimated under the natural RAG-off condition. For
each metric k in {LMS, CDS, MA}, the threshold theta_k is defined as the
empirical 95th percentile of the absolute differential score distribution:

theta_k = Q_0.95({ |D_k^X(t)| : X in {A, B}, t in CR2 })

where Q_0.95 denotes the empirical 95th percentile. The resulting theta_LMS,
theta_CDS, and theta_MA values are stored in theta_config.json together with
theta_entropy, the CR2 run_id, percentile rule, metric direction convention,
corpus/config hash, code Git SHA, and timestamp before Run B begins. No
post-CR2 modification or re-estimation is permitted during Run B or
counterfactual runs.

In Run B and counterfactual conditions, a metric shift is considered
threshold-exceeding only when the corresponding intervention-oriented
differential score exceeds its fixed CR2 threshold:

D_LMS^X(t) > theta_LMS

D_CDS^X(t) > theta_CDS

D_MA^X(t) > theta_MA

These threshold exceedances are not interpreted as independent causal proof.
They are used as pre-registered metric-level evidence components and are
interpreted only as part of the multi-metric pattern involving LMS, CDS, MA,
Node C baseline behavior, and counterfactual validation.
```

## 3. Replacement For Current MA Threshold Sentence

Current rev8.1 sentence to replace:

```text
The trigger threshold theta_MA applies to MA_assert(t) and is determined from
CR2 data as the 95th percentile of the MA_assert distribution in natural
(RAG-off) Node C responses...
```

Replacement text:

```text
The trigger threshold theta_MA applies to the intervention-oriented differential
modality score D_MA^X(t) = MA_assert_X(t) - MA_assert_C(t), rather than to the
raw MA_assert(t) value. It is estimated during CR2 as part of the unified
threshold estimation procedure described in Section 4.6 and fixed in
theta_config.json prior to Run B. No post-CR2 modification is permitted.
```

## 4. CDS Section Addendum

Suggested addition at the end of the CDS subsection:

```text
For threshold-based interpretation, CDS is converted into an
intervention-oriented differential score D_CDS^X(t) = CDS_C(t) - CDS_X(t), so
that a larger value indicates stronger movement toward the fixed policy
reference relative to the concurrent Node C baseline.
```

## 5. LMS Section Addendum

Suggested addition after the LMS_delta definitions:

```text
For threshold-based interpretation, LMS uses the intervention-oriented
differential score D_LMS^X(t) = LMS_X(t) - LMS_C(t), where X in {A, B}. This
keeps the LMS threshold on the same concurrent-baseline contrast used for the
primary causal interpretation.
```

## 6. Implementation Alignment Note

The runtime trigger policy should use the same oriented-score convention:

```text
D_LMS > theta_LMS
D_CDS > theta_CDS
D_MA  > theta_MA
```

This replaces mixed-direction raw comparisons such as:

```text
lms_delta < theta_lms
cds > theta_cds
ma_assert < theta_ma
```

The updated convention is intentionally monotone: larger oriented scores always
mean stronger intervention-oriented movement.

