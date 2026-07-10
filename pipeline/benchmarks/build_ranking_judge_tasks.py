from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


JUDGE_RUBRIC = {
    "0": "complete mismatch",
    "1": "weak surface overlap",
    "2": "some relevant skills but missing role fit",
    "3": "partial fit for role or stack",
    "4": "strong fit with minor seniority or domain gaps",
    "5": "excellent fit across stack, seniority, and domain",
}


def _load_jsonl(path: Path, kind: str) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{kind} line {line_number} must be an object")
            rows.append(row)
    if not rows:
        raise ValueError(f"{kind} input is empty")
    return rows


def _field(row: dict[str, Any], *keys: str) -> str:
    values = []
    for key in keys:
        value = row.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value is not None:
            values.append(str(value))
    return " ".join(" ".join(values).split())


def _id(row: dict[str, Any], prefix: str, index: int) -> str:
    value = row.get("id") or row.get("job_id") or row.get("candidate_id")
    if value is not None:
        return str(value)
    digest = hashlib.sha256(json.dumps(row, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{index}:{digest}"


def _prompt(job: dict[str, Any], candidate: dict[str, Any]) -> str:
    job_text = _field(job, "title", "description", "requirements", "responsibilities", "skills")
    candidate_text = _field(candidate, "title", "summary", "description", "skills", "experience", "projects")
    return (
        "You are an unbiased hiring evaluator. Score the candidate for the job from 0 to 5.\n"
        "Return only JSON with keys score and rationale. Use the rubric exactly.\n\n"
        f"Rubric: {json.dumps(JUDGE_RUBRIC, sort_keys=True)}\n\n"
        f"Job:\n{job_text}\n\n"
        f"Candidate:\n{candidate_text}"
    )


def build_tasks(
    jobs: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    max_jobs: int,
    candidates_per_job: int,
) -> list[dict[str, Any]]:
    tasks = []
    selected_jobs = jobs[:max_jobs]
    for job_index, job in enumerate(selected_jobs):
        job_id = _id(job, "job", job_index)
        ordered_candidates = sorted(
            enumerate(candidates),
            key=lambda item: hashlib.sha256(f"{job_id}:{_id(item[1], 'candidate', item[0])}".encode("utf-8")).hexdigest(),
        )[:candidates_per_job]
        for candidate_index, candidate in ordered_candidates:
            candidate_id = _id(candidate, "candidate", candidate_index)
            tasks.append({
                "task_id": hashlib.sha256(f"{job_id}:{candidate_id}".encode("utf-8")).hexdigest(),
                "job_id": job_id,
                "candidate_id": candidate_id,
                "rubric": JUDGE_RUBRIC,
                "prompt": _prompt(job, candidate),
                "expected_response_schema": {
                    "score": "integer 0..5",
                    "rationale": "short evidence-based string",
                },
            })
    return tasks


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LLM-judge tasks for candidate/job ranking pseudo-labels")
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-jobs", type=int, default=100)
    parser.add_argument("--candidates-per-job", type=int, default=5)
    args = parser.parse_args()
    if args.max_jobs <= 0 or args.candidates_per_job <= 0:
        raise ValueError("limits must be positive")
    tasks = build_tasks(
        _load_jsonl(args.jobs, "jobs"),
        _load_jsonl(args.candidates, "candidates"),
        args.max_jobs,
        args.candidates_per_job,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as target:
        for task in tasks:
            target.write(json.dumps(task, ensure_ascii=True, separators=(",", ":")) + "\n")
    print(json.dumps({"tasks": len(tasks), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
