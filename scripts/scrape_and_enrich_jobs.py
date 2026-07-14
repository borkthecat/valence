"""Fetch remote job listings from Apify and enrich their company domains safely.

The output is collection evidence, not fraud ground truth. Provider errors, missing
websites, and rate-limit responses are represented as ``unknown`` rather than a
fraud signal. Credentials are read from the environment or a local ignored file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from apify_client import ApifyClient
import requests


GENERIC_EMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "hotmail.com", "outlook.com", "yahoo.com",
    "icloud.com", "aol.com", "proton.me", "protonmail.com", "mail.com",
})
JOB_BOARD_DOMAINS = frozenset({"linkedin.com", "indeed.com", "ziprecruiter.com", "glassdoor.com", "monster.com"})
ATS_DOMAINS = frozenset({"greenhouse.io", "lever.co", "workday.com", "myworkdayjobs.com", "smartrecruiters.com", "jobvite.com", "icims.com", "ashbyhq.com"})


def load_local_environment(path: Path) -> None:
    """Load missing values from a simple local KEY=VALUE file without logging it."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def normalize_domain(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip().lower()
    if "@" in candidate and "://" not in candidate:
        candidate = candidate.rsplit("@", 1)[1]
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").rstrip(".")
    if not host or host == "localhost" or re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        return None
    return host


def first_text(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def first_url(record: dict[str, Any]) -> str | None:
    for key in ("company_website", "companyWebsite", "companyUrl", "company_url", "companyWebsiteUrl"):
        value = first_text(record, key)
        if value:
            return value
    company = record.get("company")
    if isinstance(company, dict):
        return first_text(company, "website", "url", "companyUrl")
    return None


def apply_url(record: dict[str, Any]) -> str | None:
    return first_text(record, "applyUrl", "apply_url", "applicationUrl", "application_url", "redirectUrl", "redirect_url", "jobUrl", "job_url", "url", "link")


def _domain_matches(domain: str, candidates: frozenset[str]) -> bool:
    return any(domain == candidate or domain.endswith(f".{candidate}") for candidate in candidates)


def _search_href_domain(href: str) -> str | None:
    parsed = urlparse(href)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        redirect = parse_qs(parsed.query).get("uddg", [None])[0]
        return normalize_domain(unquote(redirect)) if redirect else None
    return normalize_domain(href)


class CompanyDomainResolver:
    """Resolve company domains with explicit provenance and a bounded public-search fallback."""
    def __init__(self, cache_path: Path, search_fallback: bool, min_interval_seconds: float = 0.5) -> None:
        self.cache_path = cache_path
        self.search_fallback = search_fallback
        self.min_interval_seconds = min_interval_seconds
        self.cache = self._load_cache()
        self._last_request = 0.0

    def _load_cache(self) -> dict[str, dict[str, str | None]]:
        try:
            value = json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.exists() else {}
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def resolve(self, company_name: str, website: str | None, apply: str | None) -> dict[str, str | None]:
        direct = normalize_domain(website)
        if direct and not _domain_matches(direct, JOB_BOARD_DOMAINS | ATS_DOMAINS):
            return {"company_domain": direct, "apply_domain": normalize_domain(apply), "source": "payload_website"}
        apply_domain = normalize_domain(apply)
        if apply_domain and not _domain_matches(apply_domain, JOB_BOARD_DOMAINS | ATS_DOMAINS):
            return {"company_domain": apply_domain, "apply_domain": apply_domain, "source": "apply_url"}
        key = company_name.strip().lower()
        cached = self.cache.get(key)
        if cached is not None:
            return {**cached, "apply_domain": apply_domain}
        result = {"company_domain": None, "apply_domain": apply_domain, "source": "unresolved"}
        if self.search_fallback and key:
            delay = self.min_interval_seconds - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            try:
                response = requests.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": f"{company_name} official website"},
                    headers={"User-Agent": "ValenceResearchBot/1.0 (+https://github.com/borkthecat/valence)"},
                    timeout=5,
                )
                self._last_request = time.monotonic()
                response.raise_for_status()
                for href in re.findall(r'href=["\']([^"\']+)', response.text, flags=re.IGNORECASE):
                    domain = _search_href_domain(href)
                    if domain and not _domain_matches(domain, JOB_BOARD_DOMAINS | ATS_DOMAINS | frozenset({"duckduckgo.com"})):
                        result = {"company_domain": domain, "apply_domain": apply_domain, "source": "duckduckgo_official_site_candidate"}
                        break
            except requests.RequestException:
                pass
        self.cache[key] = {"company_domain": result["company_domain"], "source": result["source"]}
        return result


def first_contact_email(record: dict[str, Any], description: str) -> str | None:
    value = first_text(record, "contactEmail", "contact_email", "email")
    if value:
        return value.lower()
    match = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}\b", description, re.IGNORECASE)
    return match.group(0).lower() if match else None


def parse_created(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    for parser in (lambda: datetime.fromisoformat(raw).date(), lambda: datetime.strptime(raw[:10], "%Y-%m-%d").date()):
        try:
            return parser()
        except ValueError:
            pass
    return None


def _find_first(payload: object, names: set[str]) -> object | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower().replace("_", "") in names and value not in (None, ""):
                return value
        for value in payload.values():
            found = _find_first(value, names)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_first(value, names)
            if found is not None:
                return found
    return None


class WhoisJsonClient:
    def __init__(self, token: str, cache_path: Path, min_interval_seconds: float = 0.25) -> None:
        self.token = token
        self.cache_path = cache_path
        self.min_interval_seconds = min_interval_seconds
        self.cache: dict[str, dict[str, Any]] = self._load_cache()
        self._last_request = 0.0

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if not self.cache_path.exists():
            return {}
        try:
            value = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def lookup(self, domain: str) -> dict[str, Any]:
        cached = self.cache.get(domain)
        if cached is not None:
            return cached
        delay = self.min_interval_seconds - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        try:
            response = requests.get(
                "https://whoisjson.com/api/v1",
                params={"domain": domain},
                headers={"Authorization": f"TOKEN={self.token}", "Accept": "application/json"},
                timeout=12,
            )
            self._last_request = time.monotonic()
            response.raise_for_status()
            body = response.json()
            created = parse_created(_find_first(body, {"created", "creationdate", "createddate", "registereddate"}))
            registrar = _find_first(body, {"registrar", "registrarname"})
            result = {
                "status": "found",
                "created": created.isoformat() if created else None,
                "registrar": str(registrar) if registrar is not None else None,
            }
        except (requests.RequestException, ValueError):
            result = {"status": "unknown", "created": None, "registrar": None}
        self.cache[domain] = result
        return result


def enrich_record(record: dict[str, Any], whois: WhoisJsonClient, resolver: CompanyDomainResolver, today: date, low_assurance_registrars: set[str]) -> dict[str, Any]:
    company_name = first_text(record, "companyName", "company_name", "company") or ""
    description = first_text(record, "descriptionText", "description", "jobDescription", "job_description") or ""
    website = first_url(record)
    resolved = resolver.resolve(company_name, website, apply_url(record))
    domain = resolved["company_domain"]
    contact_email = first_contact_email(record, description)
    contact_domain = normalize_domain(contact_email)
    lookup = whois.lookup(domain) if domain else {"status": "not_checked", "created": None, "registrar": None}
    created = parse_created(lookup.get("created"))
    age = (today - created).days if created and created <= today else None
    registrar = lookup.get("registrar")
    registrar_key = str(registrar).strip().lower() if registrar else ""
    generic_contact = bool(contact_domain and contact_domain in GENERIC_EMAIL_DOMAINS)
    mismatch = bool(domain and contact_domain and domain != contact_domain and not contact_domain.endswith(f".{domain}"))
    signals: list[str] = []
    if age is not None and age < 30:
        signals.append("DOMAIN_NEW_UNDER_30_DAYS")
    if generic_contact:
        signals.append("GENERIC_CONTACT_EMAIL")
    if mismatch:
        signals.append("EMAIL_DOMAIN_MISMATCH")
    if registrar_key and registrar_key in low_assurance_registrars:
        signals.append("CONFIGURED_LOW_ASSURANCE_REGISTRAR")
    return {
        "source": "apify_live_listing",
        "source_job_id": first_text(record, "id", "jobId", "job_id"),
        "title": first_text(record, "title", "jobTitle", "job_title"),
        "companyName": company_name,
        "descriptionText": description,
        "posting_url": first_text(record, "url", "jobUrl", "job_url", "link"),
        "company_website": website,
        "company_domain": domain,
        "company_domain_source": resolved["source"],
        "apply_domain": resolved["apply_domain"],
        "contact_email_domain": contact_domain,
        "whois_status": lookup["status"],
        "domain_created": lookup.get("created"),
        "domain_age_days": age,
        "registrar": registrar,
        "generic_contact_email": generic_contact,
        "email_domain_mismatch": mismatch,
        "threat_signals": signals,
        "high_risk_external_signal": bool(signals),
        "label": "unknown",
        "release_gate_eligible": False,
    }


def collect_items(client: ApifyClient, actor: str, actor_input: dict[str, Any], limit: int) -> Iterable[dict[str, Any]]:
    run = client.actor(actor).call(run_input=actor_input)
    dataset_id = run.get("defaultDatasetId")
    if not isinstance(dataset_id, str) or not dataset_id:
        raise RuntimeError("Apify actor run did not provide a default dataset")
    for index, item in enumerate(client.dataset(dataset_id).iterate_items()):
        if index >= limit:
            break
        if isinstance(item, dict):
            yield item


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect live remote jobs and enrich them with cached WhoisJSON data")
    parser.add_argument("--output", type=Path, default=Path("data/raw/live_enriched_jobs.json"))
    parser.add_argument("--cache", type=Path, default=Path("data/raw/whois-json-cache.json"))
    parser.add_argument("--domain-cache", type=Path, default=Path("data/raw/company-domain-cache.json"))
    parser.add_argument("--actor", default="automation-lab/linkedin-jobs-scraper")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--actor-input", default='{"searchQuery":"remote","location":"Remote","maxJobs":200}')
    parser.add_argument("--low-assurance-registrar", action="append", default=[])
    parser.add_argument("--disable-search-fallback", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path(".env.local"))
    args = parser.parse_args()
    if not 1 <= args.limit <= 500:
        raise ValueError("--limit must be between 1 and 500")
    load_local_environment(args.env_file)
    apify_token = os.environ.get("APIFY_API_TOKEN")
    whois_token = os.environ.get("WHOIS_JSON_API_KEY")
    if not apify_token or not whois_token:
        raise RuntimeError("APIFY_API_TOKEN and WHOIS_JSON_API_KEY must be set in the environment or ignored env file")
    try:
        actor_input = json.loads(args.actor_input)
    except json.JSONDecodeError as error:
        raise ValueError("--actor-input must be a JSON object") from error
    if not isinstance(actor_input, dict):
        raise ValueError("--actor-input must be a JSON object")
    whois = WhoisJsonClient(whois_token, args.cache)
    resolver = CompanyDomainResolver(args.domain_cache, not args.disable_search_fallback)
    today = datetime.now(UTC).date()
    registrars = {value.strip().lower() for value in args.low_assurance_registrar if value.strip()}
    records = [enrich_record(item, whois, resolver, today, registrars) for item in collect_items(ApifyClient(apify_token), args.actor, actor_input, args.limit)]
    whois.save()
    resolver.save()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"schema_version": 1, "collected_at": datetime.now(UTC).isoformat(), "records": records}, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(records), "output": str(args.output), "label": "unknown", "releaseGateEligible": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
