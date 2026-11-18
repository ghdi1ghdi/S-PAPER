import json
from pathlib import Path
import pytest
import httpx
from app.providers.scholar import parse_scholar, GoogleScholarProvider
from app.providers.arxiv import parse_arxiv, arxiv_identity
from app.providers.base import ProviderError, Candidate, normalize_doi, sanitize
from app.providers.enrichment import crossref_match, clean_abstract
from app.providers.http import HTTPGateway
from app.queries import build_queries
from app.config import configured, settings
from tests.conftest import MemoryCache

FIXTURES = Path(__file__).parent / "fixtures"


def test_documented_scholar_nested_and_no_abstract():
    page = parse_scholar(json.loads((FIXTURES / "scholar.json").read_text()))
    c = page.candidates[0]
    assert c.raw["inline_links"]["cited_by"]["total"] == 14003
    assert c.raw["inline_links"]["versions"]["total"] == 6
    assert c.abstract is None and c.search_snippet and c.journal is None
    assert c.publication_year == 1977 and c.published_at is None
    assert page.next_offset == 20  # Short page still follows explicit next link.


@pytest.mark.parametrize("data", [{}, {"organic_results": None}, {"organic_results": {}}, []])
def test_bad_scholar_schema(data):
    with pytest.raises(ProviderError, match="SCHEMA_ERROR"):
        parse_scholar(data)


def test_optional_fields_and_empty():
    result = parse_scholar({"organic_results": [None, {"title": "Valid", "publication_info": None, "inline_links": [], "resources": 123}]})
    assert len(result.candidates) == 1 and result.warnings == ["missing_title"]
    assert parse_scholar({"organic_results": []}).fetched_count == 0
    assert parse_scholar({"error": "Google hasn't returned any results for this query."}).fetched_count == 0


def test_repeated_offset():
    result = parse_scholar({"organic_results": [{"title": "x"}], "serpapi_pagination": {"next": "https://evil.local?start=20"}}, 20)
    assert result.next_offset is None and result.warnings


def test_arxiv_documented_xml():
    c = parse_arxiv((FIXTURES / "arxiv.xml").read_text()).candidates[0]
    assert c.source_id == "hep-ex/0307015" and c.source_version == "v1"
    assert c.abstract and c.journal is None
    assert c.raw["journal_ref"] and c.provenance["abstract"]["preprint"]
    assert arxiv_identity("https://arxiv.org/abs/2401.12345v2") == ("2401.12345", "v2")


@pytest.mark.parametrize("xml", ["bad xml", '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#bad</id></entry></feed>', '<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'])
def test_arxiv_errors(xml):
    with pytest.raises(ProviderError):
        parse_arxiv(xml)


def test_query_and_doi():
    assert build_queries("EEG brain age", ["EEG", "brain age", "aging", "EEG"]) == {"google_scholar": "EEG brain age aging",
        "arxiv": '(ti:EEG OR abs:EEG) AND (ti:"brain age" OR abs:"brain age") AND (ti:aging OR abs:aging)'}
    # Extra keywords widen recall as one OR group; topic stopwords are not required terms.
    q = build_queries("deep learning for sleep staging", ["sleep staging", "EEG", "polysomnography"])
    assert q["google_scholar"] == "deep learning for sleep staging (EEG OR polysomnography)"
    assert q["arxiv"] == ('(ti:"sleep staging" OR abs:"sleep staging") AND (ti:deep OR abs:deep) AND (ti:learning OR abs:learning)'
                          ' AND (ti:EEG OR abs:EEG OR ti:polysomnography OR abs:polysomnography)')
    assert normalize_doi(" DOI: 10.1234/ABC(DEF). ") == "10.1234/abc(def)."
    assert normalize_doi("https://doi.org/10.1234/ABC%28d%29") == "10.1234/abc(d)"
    assert normalize_doi("not a doi") is None
    assert not configured("your_serpapi_api_key")
    assert "secret" not in json.dumps(sanitize({"api_key": "secret", "url": "https://x.org/a?token=secret"}))


def test_crossref_rejects_first_wrong_and_ambiguous():
    c = Candidate(title="Long specific brain age research title", source="google_scholar", authors=["Alice Kim"], publication_year=2024)
    good = {"title": [c.title], "DOI": "10.1234/good", "author": [{"given": "Alice", "family": "Kim"}], "published": {"date-parts": [[2024]]}}
    bad = good | {"title": ["Unrelated title"], "score": 9999, "DOI": "10.1234/bad"}
    assert crossref_match(c, [bad, good])[0]["DOI"] == "10.1234/good"
    assert crossref_match(c, [good, good | {"DOI": "10.1234/other"}])[0] is None
    # Missing authors are "no evidence"; an exact long title from the same year is enough (tier B).
    assert crossref_match(c, [good | {"author": []}])[0]["DOI"] == "10.1234/good"
    # A different author list is a conflict and blocks tier B.
    assert crossref_match(c, [good | {"author": [{"given": "Bob", "family": "Park"}]}])[0] is None
    # Year more than one apart always rejects.
    assert crossref_match(c, [good | {"published": {"date-parts": [[2020]]}}])[0] is None
    assert clean_abstract('<jats:p>Hi <b>there</b></jats:p><script>alert(1)</script>') == 'Hi there'


def test_http_retry_call_limit(monkeypatch):
    monkeypatch.setattr(settings(), "max_serpapi_requests_per_job", 2)
    gateway = HTTPGateway(cache=MemoryCache(), client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    monkeypatch.setattr(gateway, "wait", lambda seconds: None)
    with pytest.raises(ProviderError, match="CALL_BUDGET"):
        gateway.get("google_scholar", "https://serpapi.com/search", {"api_key": "secret"})
    assert gateway.usage["google_scholar"]["requests"] == 2


@pytest.mark.parametrize("status,body,code", [(401,"{}","AUTHORIZATION_ERROR"),(429,'{"error":"You have run out of searches"}',"QUOTA_EXHAUSTED"),(200,'{"error":"Unexpected upstream error"}',"UPSTREAM_BODY_ERROR"),(200,'no json',"INVALID_JSON")])
def test_http_error_classification(status, body, code):
    g = HTTPGateway(cache=MemoryCache(), client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status,text=body))))
    with pytest.raises(ProviderError, match=code):
        g.get("google_scholar", "https://serpapi.com/search", {})
    assert g.usage["google_scholar"]["requests"] == 1


def test_scholar_configuration_error():
    g = HTTPGateway(cache=MemoryCache())
    with pytest.raises(ProviderError, match="CONFIGURATION_ERROR"):
        GoogleScholarProvider(g).search("x",0,{})
    with pytest.raises(ValueError):
        GoogleScholarProvider(g,21)


def test_retry_after_and_cache(monkeypatch):
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(429,headers={'Retry-After':'7'},json={}) if len(calls)==1 else httpx.Response(200,json={'organic_results':[]})
    g=HTTPGateway(cache=MemoryCache(),client=httpx.Client(transport=httpx.MockTransport(respond)))
    waits=[]
    monkeypatch.setattr(g,'wait',waits.append)
    first=g.get('google_scholar','https://serpapi.com/search',{})
    second=g.get('google_scholar','https://serpapi.com/search',{})
    assert waits==[7] and first==second
    assert g.usage['google_scholar']=={'requests':2,'errors':1,'retries':1,'cache_hits':1}


def test_scholar_never_follows_remote_pagination_url(monkeypatch):
    monkeypatch.setattr(settings(),'serpapi_api_key','test-not-a-real-key')
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(200,json={'organic_results':[{'title':'Paper'}], 'serpapi_pagination':{'next':'http://169.254.169.254/?start=40'}})
    g=HTTPGateway(cache=MemoryCache(),client=httpx.Client(transport=httpx.MockTransport(respond)))
    p=GoogleScholarProvider(g)
    first=p.search('EEG "brain age"',0,{})
    p.search('EEG "brain age"',first.next_offset,{})
    assert [r.url.host for r in requests]==['serpapi.com','serpapi.com']
    assert requests[1].url.params['start']=='40'
