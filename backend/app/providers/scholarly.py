"""Free scholarly metadata APIs used to fill DOI / journal / ISSN / abstract gaps.

Scholar results never carry abstracts and Crossref deposits abstracts for only a minority of
works, so most collected papers had no abstract and therefore no AI summary. These enrichers
are tried in order (OpenAlex -> Europe PMC -> Semantic Scholar); each one only fills fields that
are still empty and records provenance. Identity is never guessed: title searches go through the
same conservative match_records rules as Crossref, and DOI lookups must echo the same DOI.
"""
import json
import re
from urllib.parse import quote
from ..db import now
from .base import ProviderError, normalize_doi, obj, arr, text
from .enrichment import match_records, clean_abstract, needs_enrichment


def openalex_abstract(index):
    """Rebuild plain text from OpenAlex's abstract_inverted_index {word: [positions]}."""
    if not isinstance(index, dict) or not index:
        return None
    slots = {}
    for word, positions in index.items():
        for pos in arr(positions):
            if isinstance(pos, int) and 0 <= pos < 20000:
                slots[pos] = word
    return " ".join(slots[i] for i in sorted(slots)) or None


def openalex_record(item):
    source = obj(obj(item.get("primary_location")).get("source"))
    return {"title": text(item.get("title")) or text(item.get("display_name")), "doi": item.get("doi"),
            "year": item.get("publication_year") if isinstance(item.get("publication_year"), int) else None,
            "authors": [text(obj(a.get("author")).get("display_name")) for a in arr(item.get("authorships"))
                        if isinstance(a, dict) and text(obj(a.get("author")).get("display_name"))],
            "journal": text(source.get("display_name")) if source.get("type") == "journal" else None}


def fill(c, source, basis, **values):
    changed = False
    for field, value in values.items():
        if value in (None, [], "") or getattr(c, field):
            continue
        setattr(c, field, value)
        c.provenance[field] = {"source": source, "retrieved_at": now().isoformat(), "basis": basis}
        changed = True
    return changed


class OpenAlexEnricher:
    name = "openalex"
    fields = "id,doi,title,display_name,publication_year,authorships,primary_location,abstract_inverted_index,type"

    def __init__(self, gateway):
        self.http = gateway

    def params(self, extra):
        cfg = self.http.cfg
        params = {"select": self.fields} | extra
        if cfg.crossref_mailto:
            params["mailto"] = cfg.crossref_mailto
        if getattr(cfg, "openalex_api_key", ""):
            params["api_key"] = cfg.openalex_api_key
        return params

    def enrich(self, c):
        if not needs_enrichment(c):
            return c
        if c.doi:
            try:
                item = json.loads(self.http.get(self.name, "https://api.openalex.org/works/doi:" + quote(c.doi, safe="/"),
                                                self.params({}), 86400))
            except ProviderError as exc:
                if exc.code == "NOT_FOUND":
                    return c
                raise
            if normalize_doi(item.get("doi")) != c.doi:
                return c
            basis = {"matches": ["explicit DOI"]}
        else:
            # title.search, not search: plain search also matches abstracts and full text, which
            # buries the exact work under topically similar papers. ",", ":" and "|" are filter syntax.
            query = " ".join(re.sub(r"[,:|]", " ", c.title).split())[:300]
            data = json.loads(self.http.get(self.name, "https://api.openalex.org/works",
                                            self.params({"filter": "title.search:" + query, "per_page": 5}), 86400))
            results = [x for x in arr(data.get("results")) if isinstance(x, dict)]
            item, basis = match_records(c, [(x, openalex_record(x)) for x in results])
            if not item:
                return c
        rec = openalex_record(item)
        doi = normalize_doi(rec["doi"])
        if doi and doi.startswith("10.48550/arxiv."):
            # arXiv's own DataCite DOI only restates the preprint ID. Storing it would block the
            # later Crossref lookup and the DOI-based merge with the journal version.
            doi = None
        source = obj(obj(item.get("primary_location")).get("source"))
        issns = [v for v in arr(source.get("issn")) if isinstance(v, str)] if source.get("type") == "journal" else []
        fill(c, self.name, basis, doi=doi, journal=rec["journal"], issns=issns,
             abstract=openalex_abstract(item.get("abstract_inverted_index")),
             publication_year=rec["year"], authors=rec["authors"])
        return c


class EuropePMCEnricher:
    """Biomedical abstracts (PubMed/PMC) by DOI. Only runs when the abstract is still missing."""
    name = "europepmc"

    def __init__(self, gateway):
        self.http = gateway

    def enrich(self, c):
        if c.abstract or not c.doi:
            return c
        data = json.loads(self.http.get(self.name, "https://www.ebi.ac.uk/europepmc/webservices/rest/search", {
            "query": f'DOI:"{c.doi}"', "resultType": "core", "format": "json", "pageSize": 2}, 86400))
        for item in arr(obj(data.get("resultList")).get("result")):
            if isinstance(item, dict) and normalize_doi(item.get("doi")) == c.doi:
                journal = text(obj(obj(item.get("journalInfo")).get("journal")).get("title"))
                fill(c, self.name, {"matches": ["explicit DOI"]},
                     abstract=clean_abstract(item.get("abstractText")), journal=journal)
                break
        return c


class SemanticScholarEnricher:
    """Abstract by DOI or arXiv ID. Unauthenticated access shares a small global quota, so a 429
    is treated as a soft miss rather than an error."""
    name = "semantic_scholar"

    def __init__(self, gateway):
        self.http = gateway

    def enrich(self, c):
        if c.abstract:
            return c
        if c.doi:
            key = "DOI:" + c.doi
        elif c.source == "arxiv" and c.source_id:
            key = "ARXIV:" + c.source_id
        else:
            return c
        headers = {}
        if getattr(self.http.cfg, "semantic_scholar_api_key", ""):
            headers["x-api-key"] = self.http.cfg.semantic_scholar_api_key
        try:
            item = json.loads(self.http.get(self.name, "https://api.semanticscholar.org/graph/v1/paper/" + quote(key, safe=":/"),
                                            {"fields": "title,abstract,externalIds,year"}, 86400, headers or None))
        except ProviderError as exc:
            if exc.code in ("NOT_FOUND", "RATE_LIMIT"):
                return c
            raise
        ids = obj(item.get("externalIds"))
        same = (c.doi and normalize_doi(ids.get("DOI")) == c.doi) or (
            not c.doi and c.source_id and text(ids.get("ArXiv")) == c.source_id)
        if same:
            fill(c, self.name, {"matches": ["explicit DOI" if c.doi else "explicit arXiv ID"]}, abstract=text(item.get("abstract")))
        return c
