"""Run a bounded dual-review LLM ranking pilot as silver pseudo-label evidence.

This deliberately cannot create human ground truth. It produces auditable reviewer
and adjudicator outputs that are marked ineligible for the human-label release gate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

from benchmarks.build_ranking_judge_tasks import build_tasks, _load_jsonl  # noqa: E402
from benchmarks.adjudicate_ranking_silver import adjudicate  # noqa: E402


REVIEWER_A = "You are Reviewer 1. Apply the rubric strictly from demonstrated evidence. Do not infer missing qualifications. Return only the requested JSON."
REVIEWER_B = "You are Reviewer 2. Be skeptical of unsupported claims, seniority inflation, and keyword-only overlap. Score only evidence relevant to the role. Return only the requested JSON."
ADJUDICATOR = "You are a critical adjudicator. Resolve only a material scoring disagreement using the supplied job and candidate evidence. Do not average automatically. Return only the requested JSON."


def load_local_environment(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")


def score(client: OpenAI, model: str, persona: str, prompt: str) -> dict[str, Any]:
    constrained_prompt = (
        f"{prompt}\n\n"
        "For this pilot, the score must be exactly one integer from 0 through 3: "
        "0=complete mismatch, 1=weak overlap, 2=partial fit, 3=strong fit. "
        "Return a JSON object with exactly score and rationale."
    )
    completion = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": persona},
            {"role": "user", "content": constrained_prompt},
        ],
    )
    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("LLM returned an empty response")
    result = json.loads(content)
    raw_score = result.get("score")
    if not isinstance(raw_score, int) or not 0 <= raw_score <= 3:
        raise ValueError("LLM response score must be an integer in 0..3")
    rationale = result.get("rationale")
    return {"score": raw_score, "rationale": str(rationale or ""), "model": model}


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate LLM ranking silver pseudo-labels with dual review and adjudication")
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(".benchmark-data/llm-ranking-pilot"))
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--max-jobs", type=int, default=210)
    parser.add_argument("--candidates-per-job", type=int, default=15)
    parser.add_argument("--allow-small-smoke", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path(".env.local"))
    args = parser.parse_args()
    if args.max_jobs != 210 and not args.allow_small_smoke:
        raise ValueError("the pilot must use exactly 210 jobs; use --allow-small-smoke only for a non-pilot smoke run")
    if not 10 <= args.candidates_per_job <= 20 and not args.allow_small_smoke:
        raise ValueError("the pilot requires 10 to 20 candidates per job")
    load_local_environment(args.env_file)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set in the environment or ignored env file")
    jobs = _load_jsonl(args.jobs, "jobs")
    candidates = _load_jsonl(args.candidates, "candidates")
    if len(jobs) < args.max_jobs and not args.allow_small_smoke:
        raise ValueError(f"need {args.max_jobs} jobs but only found {len(jobs)}")
    if len(candidates) < args.candidates_per_job and not args.allow_small_smoke:
        raise ValueError(f"need {args.candidates_per_job} candidates but only found {len(candidates)}")
    task_count = min(args.max_jobs, len(jobs))
    candidate_count = min(args.candidates_per_job, len(candidates))
    tasks = build_tasks(jobs, candidates, task_count, candidate_count)
    client = OpenAI(api_key=api_key)
    reviewer_a, reviewer_b, adjudicator = [], [], []
    for task in tasks:
        task_id = str(task["task_id"])
        reviewer_a.append({"task_id": task_id, **score(client, args.model, REVIEWER_A, str(task["reviewer_prompts"]["reviewer_a"]))})
        reviewer_b.append({"task_id": task_id, **score(client, args.model, REVIEWER_B, str(task["reviewer_prompts"]["reviewer_b"]))})
        if abs(reviewer_a[-1]["score"] - reviewer_b[-1]["score"]) > 1:
            prompt = f"Task:\n{task['reviewer_prompts']['reviewer_a']}\n\nReviewer 1 score: {reviewer_a[-1]['score']}\nReviewer 2 score: {reviewer_b[-1]['score']}"
            adjudicator.append({"task_id": task_id, **score(client, args.model, ADJUDICATOR, prompt)})
    labels, summary = adjudicate(
        tasks,
        {row["task_id"]: row for row in reviewer_a},
        {row["task_id"]: row for row in reviewer_b},
        {row["task_id"]: row for row in adjudicator},
    )
    for label in labels:
        label["score_scale"] = "0..3"
        label["evidence_level"] = "silver_pseudo_label"
        label["release_gate_eligible"] = False
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "tasks.jsonl", tasks)
    write_jsonl(args.output_dir / "reviewer_a.jsonl", reviewer_a)
    write_jsonl(args.output_dir / "reviewer_b.jsonl", reviewer_b)
    write_jsonl(args.output_dir / "adjudicator.jsonl", adjudicator)
    write_jsonl(args.output_dir / "consensus_labels.jsonl", labels)
    summary.update({"jobs": task_count, "candidatesPerJob": candidate_count, "model": args.model, "scoreScale": "0..3", "evidenceLevel": "silver_pseudo_label", "releaseGateEligible": False})
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
