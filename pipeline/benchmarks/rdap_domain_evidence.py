"""Credential-free domain registration evidence via the IANA RDAP bootstrap."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    from .external_provider_cache import ExternalProviderCache
except ImportError:  # direct script execution
    from external_provider_cache import ExternalProviderCache

BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"


def _json_get(url: str, timeout: float) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/rdap+json, application/json", "User-Agent": "ValenceVerification/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


class RdapDomainEvidenceProvider:
    def __init__(self, cache: ExternalProviderCache, *, timeout: float = 4.0,
                 fetch_json: Callable[[str, float], dict[str, Any]] = _json_get,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.cache, self.timeout, self.fetch_json, self.now = cache, timeout, fetch_json, now

    def lookup(self, domain: str) -> dict[str, Any]:
        normalized = domain.strip(".").casefold().encode("idna").decode("ascii")
        if "." not in normalized:
            return {"status": "unknown", "reason": "invalid_domain"}
        return self.cache.lookup("iana-rdap", normalized, ttl_seconds=86_400, fetch=lambda: self._fetch(normalized))

    def _fetch(self, domain: str) -> dict[str, Any]:
        bootstrap = self.cache.lookup("iana-rdap-bootstrap", "dns", ttl_seconds=604_800,
                                      fetch=lambda: self.fetch_json(BOOTSTRAP_URL, self.timeout))
        tld = domain.rsplit(".", 1)[-1]
        services = bootstrap.get("services", [])
        bases = next((urls for zones, urls in services if tld in {str(zone).casefold() for zone in zones}), [])
        if not bases:
            return {"status": "unknown", "reason": "unsupported_tld"}
        response = self.fetch_json(str(bases[0]).rstrip("/") + "/domain/" + quote(domain), self.timeout)
        if response.get("objectClassName") != "domain":
            return {"status": "unknown", "reason": "invalid_response"}
        registration = next((event.get("eventDate") for event in response.get("events", []) if event.get("eventAction") == "registration"), None)
        created = datetime.fromisoformat(registration.replace("Z", "+00:00")) if registration else None
        age = max(0, (self.now() - created).days) if created else None
        nameservers = sorted(item.get("ldhName", "").casefold() for item in response.get("nameservers", []) if item.get("ldhName"))
        return {"status": "found", "domain_age_days": age, "registration_date": registration,
                "domain_statuses": sorted(response.get("status", [])), "nameserver_count": len(nameservers)}
