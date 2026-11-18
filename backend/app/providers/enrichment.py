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


def title_similarity(a, b):
    return SequenceMatcher(None, norm_title(a), norm_title(b)).ratio()


def venue_matches(candidate, journal):
    """Exact journal match, or Scholar's truncated venue hint found inside the journal name."""
    if not journal:
        return False
    j = norm_title(journal)
    if candidate.journal and norm_title(candidate.journal) == j:
        return True
    hint = norm_title(candidate.raw.get("venue_hint") or "") if isinstance(candidate.raw, dict) else ""
    return len(hint) >= 4 and not hint.startswith("arxiv") and (hint in j or j in hint)


def match_records(candidate, records):
    """Pick the one record that is the same work as candidate, or None when unsure.

    records: (item, {"title", "doi", "year", "authors", "journal"}) pairs from any metadata API.
    Tiered rules (missing authors are "no evidence", never a conflict):
      A. titles >=0.94 similar with two independent supports (year, author, venue)
      B. title >=0.95, >=5 words, year within 1, and no author conflict
      C. title 0.90-0.95, >=5 words, year within 1, and first-author surname match
    Short titles (<5 words) need an exact title plus two supports. A runner-up with a different
    DOI within 0.03 similarity makes the match ambiguous and nothing is accepted.
    """
    accepted = []
    a = norm_title(candidate.title)
    words = len(a.split())
    cand_keys = author_keys(candidate.authors)
    first = author_keys(candidate.authors[:1])
    for item, rec in records:
        title, doi = text(rec.get("title")), normalize_doi(rec.get("doi"))
        if not title or not doi:
            continue
        if candidate.doi and candidate.doi != doi:
            continue
        similarity = SequenceMatcher(None, a, norm_title(title)).ratio()
        year = rec.get("year")
        evidence = []
        year_ok = candidate.publication_year is None or year is None
        if candidate.publication_year is not None and year is not None:
            if abs(candidate.publication_year - year) > 1:
                continue
            year_ok = True
            if candidate.publication_year == year:
                evidence.append("year")
        rec_keys = author_keys(rec.get("authors") or [])
        if cand_keys & rec_keys:
            evidence.append("author")
        conflict = bool(cand_keys and rec_keys and not cand_keys & rec_keys)
        if venue_matches(candidate, rec.get("journal")):
            evidence.append("journal")
        if words < 5:
            ok = similarity == 1.0 and len(evidence) >= 2
        else:
            ok = (similarity >= 0.94 and len(evidence) >= 2) \
                or (similarity >= 0.95 and year_ok and candidate.publication_year is not None and not conflict) \
                or (similarity >= 0.90 and year_ok and bool(first & rec_keys))
        if ok:
            accepted.append((similarity, item, {"title_similarity": round(similarity, 4), "matches": evidence}))
    accepted.sort(key=lambda x: x[0], reverse=True)
    if not accepted:
        return None, None
    if len(accepted) > 1 and accepted[0][0] - accepted[1][0] < 0.03:
        first = normalize_doi(records_doi(accepted[0][1], records))
        second = normalize_doi(records_doi(accepted[1][1], records))
        if first != second:
            return None, None
    return accepted[0][1], accepted[0][2]


def records_doi(item, records):
    return next((rec.get("doi") for it, rec in records if it is item), None)


def crossref_record(item):
    titles = arr(item.get("title"))
    year, _ = work_year(item)
    return {"title": text(titles[0]) if titles else None, "doi": item.get("DOI"), "year": year,
            "authors": [" ".join(filter(None, [text(x.get("given")), text(x.get("family"))]))
                        for x in arr(item.get("author")) if isinstance(x, dict)],
            "journal": next(iter(arr(item.get("container-title"))), None)}


def crossref_match(candidate, items):
    return match_records(candidate, [(item, crossref_record(item)) for item in items if isinstance(item, dict)])


def needs_enrichment(c):
    return not (c.doi and c.abstract and c.journal and c.issns)


class CrossrefMetadataEnricher:
    def __init__(self, gateway):
        self.http = gateway

    def enrich(self, c):
        if not needs_enrichment(c):
            return c
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
