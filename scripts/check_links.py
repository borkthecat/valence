from __future__ import annotations

import argparse
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag in {"a", "link"} and values.get("href"):
            self.links.append(str(values["href"]))
        if tag in {"img", "script", "source"} and values.get("src"):
            self.links.append(str(values["src"]))


def _external_status(url: str, timeout: float) -> int:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Valence-Link-Check/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        if error.code not in {403, 405}:
            return error.code
    request = urllib.request.Request(url, headers={"User-Agent": "Valence-Link-Check/1.0", "Range": "bytes=0-0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status


def _links(path: Path) -> tuple[list[str], set[str]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".html", ".htm"}:
        parser = LinkParser()
        parser.feed(text)
        return parser.links, parser.ids
    return MARKDOWN_LINK.findall(text), set()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local references and optional external HTTP links")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--external", action="store_true")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    failures: list[str] = []
    external_urls: set[str] = set()
    for path in args.paths:
        links, ids = _links(path)
        for link in links:
            parsed = urllib.parse.urlsplit(link)
            if parsed.scheme in {"http", "https"}:
                external_urls.add(link)
                continue
            if parsed.scheme in {"mailto", "tel", "data"}:
                continue
            if link.startswith("#"):
                if parsed.fragment not in ids:
                    failures.append(f"{path}: missing fragment #{parsed.fragment}")
                continue
            target = (path.parent / urllib.parse.unquote(parsed.path)).resolve()
            if parsed.path and not target.exists():
                failures.append(f"{path}: missing local target {parsed.path}")
    if args.external:
        for url in sorted(external_urls):
            if urllib.parse.urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"}:
                continue
            try:
                status = _external_status(url, args.timeout)
                if status >= 400:
                    failures.append(f"{url}: HTTP {status}")
            except Exception as error:
                failures.append(f"{url}: {type(error).__name__}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"checked {len(args.paths)} file(s), {len(external_urls)} external URL(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
