import httpx
from app.providers.base import Candidate
from app.providers.scholar import parse_scholar, parse_publication_summary, doi_from_url
from app.providers.enrichment import crossref_match
from app.providers.scholarly import (openalex_abstract, OpenAlexEnricher, EuropePMCEnricher,
                                     SemanticScholarEnricher)
from app.providers.http import HTTPGateway
from app.relevance import relevance_score
from tests.conftest import MemoryCache


def test_summary_authors_and_venue():
    assert parse_publication_summary("J Smith, K Lee, M Park… - Nature, 2020 - nature.com") == (
        ["J Smith", "K Lee", "M Park"], "Nature", True)
    assert parse_publication_summary("2020 - Springer") == ([], None, False)
    assert parse_publication_summary(None) == ([], None, False)


def test_scholar_uses_summary_authors_not_only_profiles():
    page = parse_scholar({"organic_results": [{"title": "Brain age from EEG", "link": "https://onlinelibrary.wiley.com/doi/full/10.1002/hbm.1",
        "publication_info": {"summary": "A Kim, B Lee - Human Brain Mapping, 2023 - Wiley", "authors": [{"name": "B Lee"}]}}]})
    c = page.candidates[0]
    assert c.authors == ["A Kim", "B Lee"] and c.publication_year == 2023
    assert c.raw["venue_hint"] == "Human Brain Mapping" and c.journal is None
    assert c.doi == "10.1002/hbm.1"
    assert doi_from_url("https://nature.com/articles/x") is None


def test_venue_hint_counts_as_journal_evidence():
    c = Candidate(title="Brain age estimation from resting EEG", source="google_scholar", authors=["A Kim"],
                  raw={"venue_hint": "Human Brain"})
    item = {"title": [c.title], "DOI": "10.1234/x", "author": [{"given": "Alice", "family": "Kim"}],
            "container-title": ["Human Brain Mapping"], "published": {"date-parts": [[2023]]}}
    match, basis = crossref_match(c, [item])
    assert match and set(basis["matches"]) == {"author", "journal"}


def test_tier_c_needs_first_author():
    c = Candidate(title="Brain age estimation from resting state EEG signals", source="google_scholar",
                  authors=["A Kim"], publication_year=2023)
    near = {"title": ["Brain-age estimation using resting-state EEG signal"], "DOI": "10.1234/y",
            "author": [{"family": "Kim"}], "published": {"date-parts": [[2024]]}}
    assert crossref_match(c, [near])[0]
    assert crossref_match(c, [near | {"author": [{"family": "Park"}]}])[0] is None


def gateway(handler):
    return HTTPGateway(cache=MemoryCache(), client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_openalex_fills_abstract_by_title_search():
    work = {"doi": "https://doi.org/10.1234/abc", "title": "Brain age estimation from resting EEG",
            "publication_year": 2023, "authorships": [{"author": {"display_name": "Alice Kim"}}],
            "primary_location": {"source": {"display_name": "NeuroImage", "type": "journal", "issn": ["1053-8119"]}},
            "abstract_inverted_index": {"We": [0], "estimate": [1], "brain": [2], "age": [3]}}
    seen = []
    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json={"results": [work]})
    c = Candidate(title="Brain age estimation from resting EEG", source="google_scholar", authors=["A Kim"], publication_year=2023)
    c = OpenAlexEnricher(gateway(handler)).enrich(c)
    assert c.doi == "10.1234/abc" and c.abstract == "We estimate brain age" and c.journal == "NeuroImage"
    assert c.issns == ["1053-8119"] and c.provenance["abstract"]["source"] == "openalex"
    assert seen[0].host == "api.openalex.org" and seen[0].params["filter"].startswith("title.search:Brain age")


def test_openalex_doi_mismatch_is_ignored():
    g = gateway(lambda r: httpx.Response(200, json={"doi": "https://doi.org/10.1234/other", "abstract_inverted_index": {"x": [0]}}))
    c = OpenAlexEnricher(g).enrich(Candidate(title="T", source="arxiv", doi="10.1234/abc"))
    assert c.abstract is None


def test_europepmc_and_semantic_scholar_need_same_identifier():
    epmc = gateway(lambda r: httpx.Response(200, json={"resultList": {"result": [{"doi": "10.1234/ABC", "abstractText": "<p>Found</p>"}]}}))
    c = EuropePMCEnricher(epmc).enrich(Candidate(title="T", source="google_scholar", doi="10.1234/abc"))
    assert c.abstract == "Found"
    s2 = gateway(lambda r: httpx.Response(200, json={"externalIds": {"ArXiv": "2401.00001"}, "abstract": "From S2"}))
    c = SemanticScholarEnricher(s2).enrich(Candidate(title="T", source="arxiv", source_id="2401.00001"))
    assert c.abstract == "From S2"
    limited = gateway(lambda r: httpx.Response(404, json={}))
    c = SemanticScholarEnricher(limited).enrich(Candidate(title="T", source="google_scholar", doi="10.1234/abc"))
    assert c.abstract is None


def test_openalex_abstract_rebuild():
    assert openalex_abstract({"b": [1], "a": [0, 2]}) == "a b a"
    assert openalex_abstract(None) is None


def test_relevance_ranks_on_topic_papers_first():
    topic, keys = "EEG brain age", ["EEG", "brain age", "aging"]
    on = relevance_score(topic, keys, "Brain age prediction from resting EEG", "We study aging.")
    partial = relevance_score(topic, keys, "EEG artifact removal", "Independent component analysis.")
    off = relevance_score(topic, keys, "Galaxy cluster lensing", "Dark matter halos.")
    assert on == 1.0 and 0 < partial < on and off == 0.0
    # Abstract-only mention counts, but less than a title hit; plural/-ing forms match.
    assert 0 < relevance_score("sleep spindle", [], "A detector", "Sleep spindles are detected.") < 1
    assert relevance_score("sleep spindle", [], "Detecting sleep spindles", "") == 1.0


def test_openalex_does_not_store_arxiv_datacite_doi():
    work = {"doi": "https://doi.org/10.48550/arxiv.2401.00001", "title": "Brain age estimation from resting EEG",
            "publication_year": 2024, "authorships": [{"author": {"display_name": "Alice Kim"}}],
            "abstract_inverted_index": {"Hello": [0]}}
    g = gateway(lambda r: httpx.Response(200, json={"results": [work]}))
    c = OpenAlexEnricher(g).enrich(Candidate(title=work["title"], source="arxiv", authors=["Alice Kim"], publication_year=2024))
    assert c.doi is None and c.abstract == "Hello"
