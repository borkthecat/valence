# Talent Integrity benchmark protocol

Create a `BenchmarkManifest` before running a benchmark. It binds the dataset
digest, declared split, primary and secondary metrics, threshold profile,
baseline versions, model/policy digests, evaluation commit, bootstrap seed, and
exclusions. Its canonical digest must verify before results are accepted.

The deployable `lexical_skill_overlap` baseline may use only canonical job and
candidate fields. `oracle_hard_eligibility_then_skill_overlap` reads resolved
human labels and is an upper-bound diagnostic only; it must never be a system
comparison baseline or release gate.

Before evaluation, run `python pipeline/talent_dataset_audit.py records.jsonl`.
The audit recomputes each record digest and reports structural leakage and
coverage gaps. A mismatched digest fails the audit. Evaluation reports must
carry denominators and case-resampled intervals before any gate decision.

The adapter in `pipeline/talent_review_adapter.py` is the sole supported path
from live advisory `/review` output to `TalentEvaluationSubmission`. It rejects
unknown reason codes and preserves explicit IDs, policy outcomes, uncertainty,
versions, ordering, and reproducibility metadata.
