import json
import re
from urllib.parse import urlsplit, parse_qs
from ..config import configured
from ..db import now
from .base import Candidate, SearchPage, ProviderError, text, arr, obj, safe_url, sanitize, normalize_doi


def doi_from_url(url):
    """Publisher landing pages that embed the DOI in the path (/doi/10.xxxx/...)."""
    if not isinstance(url, str):
        return None
    match = re.search(r"/doi/(?:abs/|full/|pdf/|epdf/|epub/|book/)?(10\.\d{4,9}/[^?#\s]+)", url, re.I)
    return normalize_doi(match[1].rstrip("/")) if match else None


def parse_publication_summary(summary):
    """Split Scholar's "A Author, B Author - Venue, 2020 - host" line.

    publication_info.authors only lists authors that have a Scholar profile, so the summary
    line is the only place most author names appear. Returns (authors, venue_hint, truncated).
    The venue is a hint for metadata matching only; Scholar truncates and abbreviates it, so it
    is never stored as the journal itself.
    """
    if not summary:
        return [], None, False
    parts = [p.strip() for p in re.split(r"\s+-\s+", summary)]
    if len(parts) < 2:
        return [], None, False
    author_part = parts[0]
    truncated = "…" in author_part or "..." in author_part
    authors = []
    for name in re.split(r",\s*", author_part.replace("…", "").replace("...", "")):
        name = " ".join(name.split())
        # Reject years/hosts that land in the author slot when Scholar omits authors.
        if name and re.search(r"[^\W\d_]", name) and not re.search(r"\d{4}|\.\w{2,4}$", name):
            authors.append(name)
    venue = None
    if len(parts) >= 3:
        venue = re.sub(r",?\s*(?:19|20)\d{2}\s*$", "", parts[1]).strip(" ,") or None
        if venue and (re.fullmatch(r"(?:19|20)\d{2}", venue) or "…" in venue or "..." in venue):
            venue = venue.replace("…", "").replace("...", "").strip(" ,") or None
    return authors, venue, truncated


def parse_scholar(data, offset=0):
    if not isinstance(data, dict):
        raise ProviderError("SCHEMA_ERROR")
    if data.get("error"):
        if str(data["error"]).startswith("Google hasn't returned any results"):
            return SearchPage([], None, 0)
        raise ProviderError("UPSTREAM_BODY_ERROR")
    results = data.get("organic_results")
    if not isinstance(results, list):
        # Explicit no-results state is different from an unknown response shape.
        if obj(data.get("search_information")).get("organic_results_state") == "Fully empty":
            return SearchPage([], None, 0)
        raise ProviderError("SCHEMA_ERROR")
    candidates, warnings = [], []
    for item in results:
        item = obj(item)
        title = text(item.get("title"))
        if not title:
            warnings.append("missing_title")
            continue
        publication = obj(item.get("publication_info"))
        summary = text(publication.get("summary"))
        year = None
        if summary:
            # Only one unambiguous year, no publisher/website-to-journal guessing.
            years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", summary))
            if len(years) == 1:
                year = int(next(iter(years)))
        profile_authors = [a["name"].strip() for a in arr(publication.get("authors"))
                           if isinstance(a, dict) and text(a.get("name"))]
        summary_authors, venue_hint, authors_truncated = parse_publication_summary(summary)
        authors = summary_authors or profile_authors
        for name in profile_authors:
            if name not in authors:
                authors.append(name)
        links = obj(item.get("inline_links"))
        raw = {"position": item.get("position"), "publication_info": publication,
               "venue_hint": venue_hint, "authors_truncated": authors_truncated,
               "resources": arr(item.get("resources")), "inline_links": {
                   "cited_by": obj(links.get("cited_by")), "versions": obj(links.get("versions"))}}
        doi = normalize_doi(item.get("link")) or doi_from_url(item.get("link"))
        for resource in arr(item.get("resources")):
            # Only DOI resolver URLs of this result, not DOI patterns from snippets/references.
            if doi is None and isinstance(resource, dict):
                doi = normalize_doi(resource.get("link"))
        candidate = Candidate(title=title, source="google_scholar", source_id=text(item.get("result_id")),
            source_url=safe_url(item.get("link")), authors=authors, publication_year=year,
            date_precision="year" if year else None, doi=doi, search_snippet=text(item.get("snippet")), raw=sanitize(raw))
        for field in ("title", "authors", "publication_year", "doi", "search_snippet"):
            if getattr(candidate, field):
                candidate.provenance[field] = {"source": "google_scholar", "retrieved_at": now().isoformat(),
                                               "basis": "explicit result metadata"}
        candidates.append(candidate)
    next_offset = None
    pagination = obj(data.get("serpapi_pagination")) or obj(data.get("pagination"))
    next_link = pagination.get("next") or pagination.get("next_link")
    if isinstance(next_link, str):
        try:
            value = parse_qs(urlsplit(next_link).query).get("start", [None])[0]
            if value is not None and str(value).isdigit() and offset < int(value) <= 10000:
                next_offset = int(value)
            else:
                warnings.append("invalid_or_repeated_next_offset")
        except ValueError:
            warnings.append("invalid_next_offset")
    return SearchPage(candidates, next_offset, len(results), warnings)


class GoogleScholarProvider:
    name = "google_scholar"

    def __init__(self, gateway, page_size=20):
        if not 1 <= page_size <= 20:
            raise ValueError("SerpApi num must be 1..20")
        self.http, self.page_size = gateway, page_size

    def search(self, query, offset, options):
        if not configured(self.http.cfg.serpapi_api_key):
            raise ProviderError("CONFIGURATION_ERROR")
        params = {"engine": "google_scholar", "q": query, "api_key": self.http.cfg.serpapi_api_key,
                  "hl": "en", "start": offset, "num": self.page_size, "scisbd": 2 if options.get("recent") else 0}
        for field, param in (("year_from", "as_ylo"), ("year_to", "as_yhi")):
            if options.get(field):
                params[param] = options[field]
        result = parse_scholar(json.loads(self.http.get(self.name, "https://serpapi.com/search", params)), offset)
        self.http.increment(self.name, "results", result.fetched_count)
        return result
