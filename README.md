# Valence

Valence is a security and verification layer for LLM-assisted enterprise workflows. It protects sensitive data, identifies hostile or untrusted context, and produces auditable findings. Talent Integrity is the reference application for candidate ranking, job-fraud triage, and human review.

Valence is a research preview. It is not an autonomous employment decision system and must not be described as enterprise-certified.

## Status

| Area | Current evidence | Operating status |
| --- | --- | --- |
| PII detection | GLiNER on held-out Nemotron: 74.78% precision, 55.91% recall, 63.99% F1 | Advisory only |
| Prompt-injection guard | V6 cascade pooled: 97.29% accuracy, 95.97% F1, 1.75% FPR; two sources fail | Shadow and review only |
| Job-fraud triage | Group holdout: 90.15% precision, 64.32% recall, 75.08% F1 | Precision-first review triage |
| Talent ranking | No completed human-labelled pilot | No quality claim |

Detailed measurements, datasets, and remaining evidence gates are in [BENCHMARKS.md](BENCHMARKS.md), [DATASETS.md](DATASETS.md), and [Benchmark Completion Plan](docs/BENCHMARK_COMPLETION_PLAN.md).

## Components

| Component | Path | Purpose |
| --- | --- | --- |
| Valence Core | `gateway/` | TypeScript gateway for PII tokenization, injection screening, provenance policy, audit, and observability |
| Talent Integrity | `pipeline/` | Python reference application for deterministic ranking, fraud evaluation, and bounded review |
| Human review | `review/` | Label Studio configurations and review-pack workflows |

## Quick Start

### Local Docker smoke stack

```powershell
.\START-VALENCE.ps1
.\CHECK-VALENCE.ps1
```

This starts the gateway and local pipeline stack. For a credential-free demo:

```powershell
docker compose -f docker-compose.yml -f docker-compose.local.yml --env-file .env.example up --build
```

### Development

```powershell
cd gateway
npm ci
npm run typecheck
npm test

cd ../pipeline
python -m pip install -r requirements-dev.txt
python -W error -m pytest -q
```

Copy `.env.example` to `.env` before running a non-demo stack. Keep production secrets and managed persistence outside the repository.

### Human review

Start Label Studio locally:

```powershell
.\scripts\start_hybrid_review_env.ps1
```

Open http://127.0.0.1:8081 and follow [Hybrid Human Review](docs/HYBRID_HUMAN_REVIEW.md). For raw Markdown PII input, generate strict offset-safe tasks with:

```powershell
python -m pip install -r requirements-pii-classifier.txt
python scripts/export_gliner_label_studio.py input.jsonl review-pack/gliner-tasks.json
```

The exporter normalizes text before GLiNER inference and drops spans that fail exact character-offset validation.

## Documentation

- [Gateway deployment](docs/DEPLOYMENT.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Operations and failure SLOs](docs/OPERATIONS.md)
- [Governance](docs/GOVERNANCE.md)
- [Fairness and human-review policy](docs/FAIRNESS.md)
- [Talent Integrity design](docs/TALENT_INTEGRITY.md)
- [Talent benchmark protocol](docs/TALENT_BENCHMARK_PROTOCOL.md)
- [Hybrid human review](docs/HYBRID_HUMAN_REVIEW.md)
- [Shadow-readiness execution](docs/SHADOW_READINESS_EXECUTION.md)
- [Release procedure](RELEASE.md) and [change history](CHANGE.md)

## Testing

GitHub Actions validates the TypeScript gateway, Python pipeline, Docker topology, and checked-in benchmark provenance. Run the commands above before pushing. The [release procedure](RELEASE.md) includes the full preflight.

## License

Licensed under [Apache-2.0](LICENSE). See [NOTICE](NOTICE) and [Third-Party Notices](THIRD_PARTY_NOTICES.md).
