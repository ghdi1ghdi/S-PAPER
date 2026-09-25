import json
from difflib import SequenceMatcher
from datetime import datetime, timezone
from urllib.parse import quote
from bs4 import BeautifulSoup
from ..db import now
from .base import norm_title, normalize_doi, obj, arr, text, ProviderError


def clean_abstract(value):
    if not isinstance(value, str):
        return None
    soup = BeautifulSoup(value, "html.parser")
    for node in soup(["script", "style"]):
        node.decompose()
    return soup.get_text(" ", strip=True) or None


def author_keys(authors):
    return {norm_title(a).split()[-1] for a in authors if norm_title(a)}


def work_year(item):
    for key in ("published", "published-print", "published-online", "issued"):
        parts = obj(item.get(key)).get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            value = parts[0][0]
            if isinstance(value, int) and 1500 <= value <= 2200:
                return value, parts[0]
    return None, []


def crossref_match(candidate, items):
    accepted = []
    for item in items:
        if not isinstance(item, dict):
            continue
        titles = arr(item.get("title"))
        title = text(titles[0]) if titles else None
        doi = normalize_doi(item.get("DOI"))
        if not title or not doi:
            continue
        if candidate.doi and candidate.doi != doi:
            continue
        a, b = norm_title(candidate.title), norm_title(title)
        similarity = SequenceMatcher(None, a, b).ratio()
        year, _ = work_year(item)
        authors = [" ".join(filter(None, [text(x.get("given")), text(x.get("family"))]))
                   for x in arr(item.get("author")) if isinstance(x, dict)]
        journal = next(iter(arr(item.get("container-title"))), None)
        evidence = []
        if candidate.publication_year is not None and year is not None:
            if abs(candidate.publication_year - year) > 1:
                continue
            if candidate.publication_year == year:
                evidence.append("year")
        if author_keys(candidate.authors) & author_keys(authors):
            evidence.append("author")
        if candidate.journal and journal and norm_title(candidate.journal) == norm_title(journal):
            evidence.append("journal")
        # Short/generic titles: require exact title and two independent supports.
        threshold = 1.0 if len(a.split()) < 5 else 0.94
        if similarity >= threshold and len(evidence) >= 2:
            accepted.append((similarity, item, {"title_similarity": similarity, "matches": evidence}))
    accepted.sort(key=lambda x: x[0], reverse=True)
    if not accepted:
        return None, None
    if len(accepted) > 1 and normalize_doi(accepted[0][1].get("DOI")) != normalize_doi(accepted[1][1].get("DOI")):
        if accepted[0][0] - accepted[1][0] < 0.03:
            return None, None
    return accepted[0][1], accepted[0][2]


class CrossrefMetadataEnricher:
    def __init__(self, gateway):
        self.http = gateway

    def enrich(self, c):
        mailto = self.http.cfg.crossref_mailto
        headers = {"User-Agent": f"S-PAPER/0.1 (metadata enrichment; mailto:{mailto or 'not-configured'})"}
        params = {"mailto": mailto} if mailto else {}
        if c.doi:
            try:
                data = json.loads(self.http.get("crossref", "https://api.crossref.org/works/" + quote(c.doi, safe=""), params, 86400, headers))
            except ProviderError as exc:
                if exc.code == "NOT_FOUND":
                    return c  # Other DOI registries remain valid.
                raise
            item, basis = obj(data.get("message")), {"matches": ["explicit DOI"]}
            if normalize_doi(item.get("DOI")) != c.doi:
                return c
        else:
            params |= {"query.bibliographic": " ".join(filter(None, [c.title, " ".join(c.authors[:2]), str(c.publication_year or "")])), "rows": 5}
            data = json.loads(self.http.get("crossref", "https://api.crossref.org/works", params, 86400, headers))
            item, basis = crossref_match(c, arr(obj(data.get("message")).get("items")))
            if not item:
                return c
        c.doi = c.doi or normalize_doi(item.get("DOI"))
        journals = arr(item.get("container-title"))
        values = {"doi": c.doi, "journal": text(journals[0]) if journals and item.get("type") == "journal-article" else None,
                  "issns": [v for v in arr(item.get("ISSN")) if isinstance(v, str)],
                  "abstract": clean_abstract(item.get("abstract"))}
        year, parts = work_year(item)
        values["publication_year"] = year
        for field, value in values.items():
            if value is not None and value != [] and (not getattr(c, field) or field in ("doi", "journal", "publication_year")):
                setattr(c, field, value)
                c.provenance[field] = {"source": "crossref", "retrieved_at": now().isoformat(), "basis": basis}
        if year:
            c.published_at = None
            c.date_precision = "year" if len(parts) == 1 else "month" if len(parts) == 2 else "day"
            if len(parts) >= 3:
                try:
                    c.published_at = datetime(*parts[:3], tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    pass
            c.provenance["published_at"] = {"source": "crossref", "date_parts": parts, "retrieved_at": now().isoformat(), "basis": basis}
        return c
