from sqlalchemy import select, func
from app.collection import CollectionService, save_candidate, recount, find_paper
from app.providers.base import Candidate, SearchPage, ProviderError
from app.models import Paper, PaperSource, Subscription, CollectionJob
from app.jobs import subscription_snapshot, create_job, dispatch_due
from app.db import now
from app.providers.http import HTTPGateway
from app.config import settings
from tests.conftest import MemoryCache


class Provider:
    def __init__(self, name, pages):
        self.name, self.pages, self.calls = name, pages, []
    def search(self, query, offset, options):
        self.calls.append(offset)
        result = self.pages[offset]
        if isinstance(result, Exception):
            raise result
        return result


def candidate(id_, source="google_scholar", **kwargs):
    return Candidate(title=f"Specific brain age estimation research number {id_}", source=source, source_id=str(id_), **kwargs)


def service(db, job, providers):
    return CollectionService(db, job, providers=providers, enrichers=[], gateway=HTTPGateway(cache=MemoryCache()))


def test_combined_target_and_source_priority(db, job):
    job.snapshot = job.snapshot | {"papers_per_cycle": 2}
    a = Provider("google_scholar", {0: SearchPage([candidate("a"),candidate("b"),candidate("c")],20,3)})
    b = Provider("arxiv", {0: SearchPage([candidate("d","arxiv")],20,1)})
    result = service(db,job,[a,b]).run()
    assert result.counts["new_count"] == 2 and result.counts["fetched_count"] == 4
    assert a.calls == b.calls == [0]
    assert set(db.scalars(select(PaperSource.source))) == {"google_scholar"}


def test_duplicates_continue_and_global_new_link(db, job, sub):
    save_candidate(db,job,candidate("a",doi="10.1234/test"))
    job.status = "success"
    db.commit()
    second = Subscription(user_id=sub.user_id, **subscription_snapshot(sub))
    db.add(second); db.commit()
    j,_ = create_job(db,second.id)
    j.snapshot = j.snapshot | {"papers_per_cycle":2, "enabled_sources":["google_scholar"]}
    provider = Provider("google_scholar", {0:SearchPage([candidate("a",doi="10.1234/test")],20,1),20:SearchPage([candidate("b")],None,1)})
    result = service(db,j,[provider]).run()
    assert result.counts["new_count"] == 2 and result.counts["global_inserted_count"] == 1
    assert db.scalar(select(func.count()).select_from(Paper)) == 2
    # Another cycle sees duplicate first page, still reaches the second page.
    j2,_ = create_job(db,second.id)
    j2.snapshot = j2.snapshot | {"papers_per_cycle":1,"enabled_sources":["google_scholar"]}
    provider = Provider("google_scholar", {0:SearchPage([candidate("a",doi="10.1234/test")],20,1),20:SearchPage([candidate("c")],None,1)})
    service(db,j2,[provider]).run()
    assert provider.calls == [0,20] and j2.counts["duplicate_count"] == 1 and j2.counts["new_count"] == 1


def test_source_failure_preserves_success(db,job):
    a=Provider("google_scholar",{0:ProviderError("CONFIGURATION_ERROR")})
    b=Provider("arxiv",{0:SearchPage([candidate("2401.12345","arxiv")],None,1)})
    service(db,job,[a,b]).run()
    assert job.status == "partial" and job.counts["new_count"] == 1
    assert job.provider_states["google_scholar"]["reason"] == "CONFIGURATION_ERROR"


def test_empty_success(db,job):
    service(db,job,[Provider("arxiv",{0:SearchPage([],None,0)})]).run()
    assert job.status == "success" and job.stop_reason == "no_new_results"


def test_doi_merge_arxiv_versions_and_conflicts(db,job):
    p=save_candidate(db,job,candidate("a",doi="10.1234/shared"))
    q=save_candidate(db,job,candidate("2401.12345","arxiv",source_version="v1",doi="10.1234/shared",abstract="Actual abstract"))
    r=save_candidate(db,job,candidate("2401.12345","arxiv",source_version="v2",doi="10.1234/shared"))
    assert p.id == q.id == r.id
    assert recount(db,job)["new_count"] == 1
    assert db.scalar(select(func.count()).select_from(PaperSource)) == 2
    assert find_paper(db,candidate("other",doi="10.1234/different",authors=["Kim"],publication_year=2024)) is None
    # Source conflict must not silently merge.
    import pytest
    with pytest.raises(ProviderError, match="CONFLICTING_DOI"):
        find_paper(db,candidate("a",doi="10.1234/conflict"))


def test_budget_and_replayed_discoveries(db,job,monkeypatch):
    monkeypatch.setattr(settings(),"max_search_pages_per_source",1)
    a=Provider("arxiv",{0:SearchPage([candidate("a","arxiv")],20,1)})
    service(db,job,[a]).run()
    assert job.status == "partial" and job.counts["new_count"] == 1
    save_candidate(db,job,candidate("a","arxiv"))
    assert recount(db,job)["new_count"] == 1


def test_repeated_page_terminates(db,job):
    page=SearchPage([candidate("a","arxiv")],20,1)
    a=Provider("arxiv",{0:page,20:page})
    service(db,job,[a]).run()
    assert a.calls == [0,20] and job.status == "partial"
    assert "arxiv:REPEATED_PAGE" in job.warnings


def test_dispatch_no_duplicate_and_one_catchup(db,sub):
    from datetime import timedelta
    sub.next_run_at = now()-timedelta(days=50)
    db.commit()
    dispatch_due(db); dispatch_due(db)
    assert db.scalar(select(func.count()).select_from(CollectionJob)) == 1
    existing, created = create_job(db,sub.id)
    assert not created and sub.next_run_at > now()


def test_checkpoint_resumes_without_refetch_or_recount(db,job):
    from dataclasses import asdict
    c=candidate('recovered','arxiv')
    save_candidate(db,job,c)
    job.snapshot=job.snapshot | {'enabled_sources':['arxiv'],'papers_per_cycle':1}
    job.status='running'
    job.provider_states={'arxiv':{'pages':1,'offsets':[0],'fingerprints':['old'],'status':'success','pending_offset':0,'next_offset':20}}
    job.checkpoint={'arxiv':{'candidates':[asdict(c)],'next_offset':20,'fetched_count':1,'warnings':[]}}
    job.counts={'fetched_count':1}
    db.commit()
    provider=Provider('arxiv',{})
    service(db,job,[provider]).run()
    assert provider.calls==[] and job.counts['new_count']==1 and job.counts['fetched_count']==1
    assert job.checkpoint=={}


def test_empty_page_stops_even_with_next(db,job):
    provider=Provider('arxiv',{0:SearchPage([],20,0)})
    service(db,job,[provider]).run()
    assert provider.calls==[0] and job.status=='success'


def test_unknown_year_does_not_fuzzy_merge(db,job):
    p=save_candidate(db,job,Candidate(title='Same fairly long title about brain aging',source='google_scholar',source_id='a',authors=['A Kim']))
    c=Candidate(title=p.title,source='google_scholar',source_id='b',authors=['A Kim'])
    assert find_paper(db,c) is None
