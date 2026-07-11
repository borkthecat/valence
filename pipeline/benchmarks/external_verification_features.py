from __future__ import annotations

import argparse
import csv
import json
import os
import re
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b", re.IGNORECASE)
URL_RE = re.compile(r"\bhttps?://[^\s<>()\"']+", re.IGNORECASE)
_CACHE_MISS = object()


@dataclass(frozen=True, slots=True)
class VerificationFeatures:
    record_id: str
    company_domain: str
    contact_email_domain: str
    posting_domain: str
    email_domain_mismatch: bool
    posting_domain_mismatch: bool
    company_domain_live: bool | None
    posting_url_live: bool | None
    domain_similarity: float | None
    verification_risk_score: float
    evidence_markers: list[str]


def _text(row: dict[str, str], key: str) -> str:
    return " ".join((row.get(key) or "").split())


def _normalize_domain(value: str) -> str:
    value = value.strip().lower()
    if not value:
        return ""
    if "://" in value:
        value = urlparse(value).netloc
    value = value.split("@")[-1].split("/")[0].split(":")[0].strip(".")
    return value[4:] if value.startswith("www.") else value


def _first_email_domain(text: str) -> str:
    match = EMAIL_RE.search(text)
    return _normalize_domain(match.group(1)) if match else ""


def _first_url(text: str) -> str:
    match = URL_RE.search(text)
    return match.group(0).rstrip(".,);") if match else ""


def _registrable_hint(domain: str) -> str:
    parts = [part for part in _normalize_domain(domain).split(".") if part]
    return ".".join(parts[-2:])


def _domain_similarity(left: str, right: str) -> float | None:
    left_hint, right_hint = _registrable_hint(left), _registrable_hint(right)
    if not left_hint or not right_hint:
        return None
    return round(SequenceMatcher(None, left_hint, right_hint).ratio(), 6)


def _domain_live(domain: str, timeout: float) -> bool | None:
    if not domain:
        return None
    try:
        socket.getaddrinfo(domain, None, 0, 0, 0, 0)
        return True
    except socket.gaierror as error:
        return False if error.errno == socket.EAI_NONAME else None
    except (socket.timeout, OSError):
        return None


def _url_live(url: str, timeout: float) -> bool | None:
    if not url:
        return None
    context = ssl.create_default_context()
    for method in ("HEAD", "GET"):
        try:
            request = Request(url, method=method, headers={"User-Agent": "ValenceVerification/1.0"})
            with urlopen(request, timeout=timeout, context=context) as response:
                return response.status != 404
        except HTTPError as error:
            return False if error.code == 404 else True
        except (URLError, TimeoutError, OSError):
            continue
    return None


class LivenessChecker:
    """Deduplicated, bounded probes with persistent TTL caching and neutral failures."""

    def __init__(self, *, timeout: float, max_workers: int = 4, retries: int = 2,
                 backoff_seconds: float = 0.25, cache_path: Path | None = None,
                 cache_ttl_seconds: float = 86_400.0, max_probes: int = 250) -> None:
        self.timeout, self.max_workers = timeout, max_workers
        self.retries, self.backoff_seconds = retries, backoff_seconds
        self.cache_path, self.cache_ttl_seconds, self.max_probes = cache_path, cache_ttl_seconds, max_probes
        self._probes_started = 0
        self._entries = self._load_cache()

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if self.cache_path is None or not self.cache_path.exists():
            return {}
        try:
            entries = json.loads(self.cache_path.read_text(encoding="utf-8")).get("entries", {})
            return entries if isinstance(entries, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _cached(self, key: str) -> bool | None | object:
        entry = self._entries.get(key)
        if entry is None or entry.get("expires_at", 0) <= time.time():
            return _CACHE_MISS
        result = entry.get("result")
        return result if isinstance(result, bool) else None

    def _store(self, key: str, result: bool | None) -> None:
        self._entries[key] = {"result": result, "expires_at": time.time() + self.cache_ttl_seconds}

    def save(self) -> None:
        if self.cache_path is None:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        temporary.write_text(json.dumps({"version": 1, "entries": self._entries}, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.cache_path)

    def _probe(self, kind: str, value: str) -> bool | None:
        probe = _domain_live if kind == "domain" else _url_live
        for attempt in range(self.retries + 1):
            result = probe(value, self.timeout)
            if result is not None:
                return result
            if attempt < self.retries:
                time.sleep(self.backoff_seconds * (2 ** attempt))
        return None

    def prefetch(self, domains: set[str], urls: set[str]) -> None:
        targets = [("domain", value) for value in domains if value]
        targets += [("url", value) for value in urls if value]
        pending = [(kind, value) for kind, value in targets if self._cached(f"{kind}:{value}") is _CACHE_MISS]
        remaining = self.max_probes - self._probes_started
        pending = sorted(set(pending))[:max(0, remaining)]
        if not pending:
            return
        self._probes_started += len(pending)
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._probe, kind, value): (kind, value) for kind, value in pending}
            for future in as_completed(futures):
                kind, value = futures[future]
                self._store(f"{kind}:{value}", future.result())
        self.save()

    def domain_live(self, domain: str) -> bool | None:
        return self._get("domain", domain)

    def url_live(self, url: str) -> bool | None:
        return self._get("url", url)

    def _get(self, kind: str, value: str) -> bool | None:
        result = self._cached(f"{kind}:{value}")
        if result is _CACHE_MISS and self._probes_started < self.max_probes:
            self.prefetch({value} if kind == "domain" else set(), {value} if kind == "url" else set())
            result = self._cached(f"{kind}:{value}")
        return None if result is _CACHE_MISS else result


def _row_blob(row: dict[str, str]) -> str:
    return "\n".join(str(value or "") for value in row.values())


def _source_values(row: dict[str, str]) -> tuple[str, str, str]:
    blob = _row_blob(row)
    company_domain = _normalize_domain(_text(row, "company_domain") or _text(row, "company_website") or _text(row, "company_url") or _first_url(_text(row, "company_profile")))
    posting_url = _text(row, "posting_url") or _text(row, "job_url") or _first_url(blob)
    return company_domain, posting_url, _normalize_domain(posting_url)


def extract_features(row: dict[str, str], *, record_id: str, check_liveness: bool = False,
                     timeout: float = 2.0, liveness_checker: LivenessChecker | None = None) -> VerificationFeatures:
    blob = _row_blob(row)
    company_domain, posting_url, posting_domain = _source_values(row)
    contact_email_domain = _normalize_domain(_text(row, "contact_email_domain") or _text(row, "poster_email_domain") or _first_email_domain(blob))
    similarity = _domain_similarity(company_domain, contact_email_domain)
    email_mismatch = bool(company_domain and contact_email_domain and _registrable_hint(company_domain) != _registrable_hint(contact_email_domain))
    posting_mismatch = bool(company_domain and posting_domain and _registrable_hint(company_domain) != _registrable_hint(posting_domain))
    company_live = liveness_checker.domain_live(company_domain) if liveness_checker and company_domain else _domain_live(company_domain, timeout) if check_liveness else None
    posting_live = liveness_checker.url_live(posting_url) if liveness_checker and posting_url else _url_live(posting_url, timeout) if check_liveness else None
    markers, risk = [], 0.0
    if company_domain: markers.append("HAS_COMPANY_DOMAIN")
    else: markers.append("MISSING_COMPANY_DOMAIN"); risk += 0.18
    if contact_email_domain: markers.append("HAS_CONTACT_EMAIL_DOMAIN")
    if email_mismatch: markers.append("EMAIL_DOMAIN_MISMATCH"); risk += 0.32
    elif company_domain and contact_email_domain: markers.append("EMAIL_DOMAIN_MATCH")
    if posting_domain: markers.append("HAS_POSTING_URL")
    if posting_mismatch: markers.append("POSTING_DOMAIN_MISMATCH"); risk += 0.20
    elif company_domain and posting_domain: markers.append("POSTING_DOMAIN_MATCH")
    if company_live is False: markers.append("COMPANY_DOMAIN_NOT_LIVE"); risk += 0.20
    elif company_live is True: markers.append("COMPANY_DOMAIN_LIVE")
    else: markers.append("COMPANY_DOMAIN_LIVENESS_UNKNOWN") if check_liveness else None
    if posting_live is False: markers.append("POSTING_URL_NOT_LIVE"); risk += 0.10
    elif posting_live is True: markers.append("POSTING_URL_LIVE")
    else: markers.append("POSTING_URL_LIVENESS_UNKNOWN") if check_liveness and posting_url else None
    if similarity is not None and similarity < 0.75: markers.append("LOW_DOMAIN_SIMILARITY"); risk += 0.10
    return VerificationFeatures(record_id, company_domain, contact_email_domain, posting_domain, email_mismatch, posting_mismatch, company_live, posting_live, similarity, round(min(1.0, risk), 6), markers)


def _checker(rows: list[dict[str, str]], args: Any) -> LivenessChecker | None:
    if not args.check_liveness:
        return None
    checker = LivenessChecker(timeout=args.timeout, max_workers=args.max_workers, retries=args.retries, backoff_seconds=args.backoff_seconds, cache_path=args.cache_path, cache_ttl_seconds=args.cache_ttl_hours * 3600, max_probes=args.max_probes)
    domains, urls = set(), set()
    for row in rows:
        domain, url, _ = _source_values(row)
        domains.add(domain); urls.add(url)
    checker.prefetch(domains, urls)
    return checker


def _rows(input_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    if not rows: raise ValueError("input CSV is empty")
    return rows, [key for key in rows[0] if key is not None]


def enrich_csv(input_path: Path, output_path: Path, args: Any) -> dict[str, Any]:
    rows, fieldnames = _rows(input_path); checker = _checker(rows, args)
    extra = ["verification_company_domain", "verification_contact_email_domain", "verification_posting_domain", "verification_email_domain_mismatch", "verification_posting_domain_mismatch", "verification_company_domain_live", "verification_posting_url_live", "verification_domain_similarity", "verification_risk_score", "verification_evidence_markers"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=[*fieldnames, *extra]); writer.writeheader()
        for index, row in enumerate(rows):
            feature = extract_features(row, record_id=_text(row, "job_id") or str(index), check_liveness=args.check_liveness, timeout=args.timeout, liveness_checker=checker)
            writer.writerow({**row, "verification_company_domain": feature.company_domain, "verification_contact_email_domain": feature.contact_email_domain, "verification_posting_domain": feature.posting_domain, "verification_email_domain_mismatch": int(feature.email_domain_mismatch), "verification_posting_domain_mismatch": int(feature.posting_domain_mismatch), "verification_company_domain_live": "" if feature.company_domain_live is None else int(feature.company_domain_live), "verification_posting_url_live": "" if feature.posting_url_live is None else int(feature.posting_url_live), "verification_domain_similarity": "" if feature.domain_similarity is None else feature.domain_similarity, "verification_risk_score": feature.verification_risk_score, "verification_evidence_markers": " ".join(feature.evidence_markers)})
    return {"records": len(rows), "output": str(output_path), "livenessChecked": args.check_liveness}


def export_jsonl(input_path: Path, output_path: Path, args: Any) -> dict[str, Any]:
    rows, _ = _rows(input_path); checker = _checker(rows, args); output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as target:
        for index, row in enumerate(rows):
            feature = extract_features(row, record_id=_text(row, "job_id") or str(index), check_liveness=args.check_liveness, timeout=args.timeout, liveness_checker=checker)
            target.write(json.dumps(asdict(feature), ensure_ascii=True, separators=(",", ":")) + "\n")
    return {"records": len(rows), "output": str(output_path), "livenessChecked": args.check_liveness}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build external verification features for job fraud experiments")
    parser.add_argument("--input", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--format", choices=("csv", "jsonl"), default="csv"); parser.add_argument("--check-liveness", action="store_true")
    parser.add_argument("--timeout", type=float, default=2.0); parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=2); parser.add_argument("--backoff-seconds", type=float, default=0.25)
    parser.add_argument("--cache-path", type=Path, default=Path(".benchmark-data/verification-liveness-cache.json")); parser.add_argument("--cache-ttl-hours", type=float, default=24.0); parser.add_argument("--max-probes", type=int, default=250)
    args = parser.parse_args()
    if args.timeout <= 0 or args.max_workers <= 0 or args.retries < 0 or args.backoff_seconds < 0 or args.cache_ttl_hours <= 0 or args.max_probes <= 0: raise ValueError("liveness limits must be positive; --retries may be zero")
    summary = enrich_csv(args.input, args.output, args) if args.format == "csv" else export_jsonl(args.input, args.output, args)
    print(json.dumps(summary, indent=2, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
