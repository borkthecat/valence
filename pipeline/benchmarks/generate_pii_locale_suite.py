from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

DEFAULT_LOCALES = ("en_US", "es_ES", "fr_FR", "de_DE", "ja_JP", "ar_AA")


def _record(prefix: str, value: str, label: str, locale: str, index: int) -> dict[str, object]:
    text = f"{prefix}{value} is recorded."
    start = len(prefix)
    return {
        "id": f"synthetic:{locale}:{index}:{label}",
        "text": text,
        "entities": [{"start": start, "end": start + len(value), "label": label}],
        "provenance": {"generator": "Faker", "locale": locale, "synthetic": True, "releaseEvidence": False},
    }


def generate(records_per_locale: int, locales: tuple[str, ...], seed: int) -> list[dict[str, object]]:
    try:
        from faker import Faker
    except ImportError as error:
        raise RuntimeError("Faker is required; install requirements-benchmark.txt") from error
    Faker.seed(seed)
    records: list[dict[str, object]] = []
    for locale in locales:
        fake = Faker(locale)
        fake.seed_instance(seed + sum(ord(character) for character in locale))
        factories: tuple[tuple[str, str, Callable[[], str]], ...] = (
            ("Contact ", "PERSON_NAME", fake.name),
            ("Email ", "EMAIL", fake.email),
            ("Phone ", "PHONE_NUMBER", fake.phone_number),
            ("Address ", "STREET_ADDRESS", fake.address),
            ("Birth date ", "DATE_OF_BIRTH", lambda: fake.date_of_birth(minimum_age=18, maximum_age=90).isoformat()),
            ("Employee id ", "EMPLOYEE_ID", lambda: fake.bothify(text="EMP-####-????").upper()),
            ("Password: ", "PASSWORD", lambda: "Aa7!" + fake.bothify(text="??????????????")),
            ("IP ", "IP_ADDRESS", fake.ipv4_public),
        )
        for index in range(records_per_locale):
            prefix, label, factory = factories[index % len(factories)]
            records.append(_record(prefix, " ".join(factory().split()), label, locale, index))
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic multilingual synthetic PII exact-span fixtures")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--records-per-locale", type=int, default=200)
    parser.add_argument("--locales", default=",".join(DEFAULT_LOCALES))
    parser.add_argument("--seed", type=int, default=20260714)
    args = parser.parse_args()
    locales = tuple(item.strip() for item in args.locales.split(",") if item.strip())
    if args.records_per_locale <= 0 or not locales:
        raise ValueError("records-per-locale and locales must be non-empty")
    records = generate(args.records_per_locale, locales, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(record, ensure_ascii=True) + "\n" for record in records), encoding="utf-8")
    print(json.dumps({"records": len(records), "locales": locales, "syntheticReleaseEvidence": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
