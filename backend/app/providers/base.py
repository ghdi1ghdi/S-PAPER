from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
import hashlib
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, unquote


class ProviderError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def obj(value):
    return value if isinstance(value, dict) else {}


def arr(value):
    return value if isinstance(value, list) else []


def norm_title(value):
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold()))


def normalize_doi(value):
    value = text(value)
    if not value:
        return None
    value = re.sub(r"^doi:\s*", "", value, flags=re.I).strip()
    if re.match(r"https?://(?:dx\.)?doi\.org/", value, re.I):
        value = unquote(urlsplit(value).path.lstrip("/"))
    return value.casefold() if re.fullmatch(r"10\.\d{4,9}/\S+", value) else None


def safe_url(value):
    value = text(value)
    if not value:
        return None
    try:
        u = urlsplit(value)
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
            return None
        safe_params = [(k, v) for k, v in parse_qsl(u.query) if k.lower() in {"id", "doi", "article_id", "pii", "pmid", "pid", "cites", "cluster"}]
        return urlunsplit((u.scheme, u.netloc, u.path, urlencode(safe_params), ""))
    except ValueError:
        return None


def sanitize(value):
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()
                if not any(x in k.lower() for x in ("key", "token", "secret", "authorization", "cookie"))}
    if isinstance(value, list):
        return [sanitize(x) for x in value]
    if isinstance(value, str):
        return re.sub(r'https?://[^\s<>"\']+', lambda m: safe_url(m.group()) or "[redacted]", value)
    return value


@dataclass
class Candidate:
    title: str
    source: str
    source_id: str | None = None
    source_version: str | None = None
    source_url: str | None = None
    authors: list[str] = field(default_factory=list)
    journal: str | None = None
    issns: list[str] = field(default_factory=list)
    publication_year: int | None = None
    published_at: datetime | None = None
    date_precision: str | None = None
    doi: str | None = None
    abstract: str | None = None
    search_snippet: str | None = None
    raw: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)

    def fingerprint(self):
        # Internal identity, never presented as a provider-issued ID.
        import json
        return hashlib.sha256(json.dumps([self.source, self.source_id, self.source_url,
            norm_title(self.title), self.publication_year, self.authors], ensure_ascii=False).encode()).hexdigest()


@dataclass
class SearchPage:
    candidates: list[Candidate]
    next_offset: int | None
    fetched_count: int
    warnings: list[str] = field(default_factory=list)


class PaperSearchProvider(Protocol):
    name: str
    def search(self, query: str, offset: int, options: dict) -> SearchPage: ...


class MetadataEnricher(Protocol):
    def enrich(self, candidate: Candidate) -> Candidate: ...


class SummaryProvider(Protocol):
    def summarize(self, paper): ...


class JournalMetricProvider(Protocol):
    def lookup(self, paper): ...
