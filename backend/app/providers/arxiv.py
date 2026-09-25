import re
from datetime import datetime
from defusedxml import ElementTree as ET
from ..db import now
from .base import Candidate, SearchPage, ProviderError, normalize_doi, safe_url

NS = {"a": "http://www.w3.org/2005/Atom", "ar": "http://arxiv.org/schemas/atom",
      "o": "http://a9.com/-/spec/opensearch/1.1/"}


def arxiv_identity(value):
    value = re.sub(r"^https?://(?:export\.)?arxiv\.org/(?:abs|pdf)/", "", value or "").removesuffix(".pdf")
    match = re.fullmatch(r"((?:\d{4}\.\d{4,5})|(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7}))(v\d+)?", value)
    return (match[1], match[2]) if match else (None, None)


def parse_arxiv(xml, offset=0, page_size=20):
    try:
        root = ET.fromstring(xml)
    except Exception:
        raise ProviderError("INVALID_XML") from None
    if root.tag != "{" + NS["a"] + "}feed":
        raise ProviderError("SCHEMA_ERROR")
    candidates, warnings = [], []
    entries = root.findall("a:entry", NS)
    for entry in entries:
        get = lambda key: (entry.findtext(key, default="", namespaces=NS) or "").strip()
        if "/api/errors" in get("a:id"):
            raise ProviderError("ARXIV_API_ERROR")
        title = get("a:title")
        if not title:
            warnings.append("missing_title")
            continue
        identity, version = arxiv_identity(get("a:id"))
        published = None
        try:
            published = datetime.fromisoformat(get("a:published").replace("Z", "+00:00"))
        except ValueError:
            pass
        c = Candidate(title=title, source="arxiv", source_id=identity, source_version=version,
            source_url=safe_url(get("a:id")), authors=[x.text.strip() for x in entry.findall("a:author/a:name", NS) if x.text],
            doi=normalize_doi(get("ar:doi")), abstract=get("a:summary") or None,
            publication_year=published.year if published else None, published_at=published,
            date_precision="day" if published else None,
            raw={"id": get("a:id"), "published": get("a:published"), "updated": get("a:updated"),
                 "journal_ref": get("ar:journal_ref"), "abstract": get("a:summary"), "title": title, "doi": get("ar:doi"),
                 "links": [safe_url(x.attrib.get("href")) for x in entry.findall("a:link", NS)]})
        for field in ("title", "authors", "doi", "abstract", "publication_year", "published_at"):
            if getattr(c, field):
                c.provenance[field] = {"source": "arxiv", "retrieved_at": now().isoformat(),
                    "basis": "explicit Atom field; year uses first submission date", "preprint": True}
        candidates.append(c)
    try:
        total = int(root.findtext("o:totalResults", namespaces=NS))
    except (ValueError, TypeError):
        raise ProviderError("SCHEMA_ERROR") from None
    return SearchPage(candidates, offset + page_size if entries and offset + page_size < total else None, len(entries), warnings)


class ArxivProvider:
    name = "arxiv"

    def __init__(self, gateway, page_size=20):
        self.http, self.page_size = gateway, page_size

    def search(self, query, offset, options):
        clauses = []
        if options.get("date_from"):
            clauses.append(f'submittedDate:[{options["date_from"]}0000 TO 300001010000]')
        if options.get("year_from") or options.get("year_to"):
            clauses.append(f'submittedDate:[{options.get("year_from") or 1500}01010000 TO {options.get("year_to") or 2200}12312359]')
        if clauses:
            query = f"({query}) AND " + " AND ".join(clauses)
        body = self.http.get(self.name, "https://export.arxiv.org/api/query", {
            "search_query": query, "start": offset, "max_results": self.page_size,
            "sortBy": "submittedDate" if options.get("recent") else "relevance", "sortOrder": "descending"}, ttl=86400)
        return parse_arxiv(body, offset, self.page_size)
