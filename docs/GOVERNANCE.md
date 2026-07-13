# Model and Data Governance

Each released model or rule bundle requires a model card covering intended use, prohibited use, training sources, version, thresholds, subgroup results, known failures, and rollback identifier. Each dataset requires a dataset card covering origin, license, collection period, label process, sensitive fields, exclusions, splits, contamination checks, and checksum.

Benchmark manifests must pin dataset, adapter, code, model, thresholds, random seed, and environment. Never tune on the reported held-out set. Record changes to schemas, policies, thresholds, providers, and evaluation gates in a decision log.

Production promotion follows: offline gates, red-team fixtures, shadow traffic, human review, signed approval, canary, monitored rollout. Rollback must restore the previous model, thresholds, policy, and adapter together. Drift monitoring covers input schema, source mix, score distribution, block/review/allow rates, reviewer disagreement, subgroup gaps, and cost. Human overrides are audit evidence, not automatic training truth.
