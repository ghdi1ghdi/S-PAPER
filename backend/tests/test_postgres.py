"""Opt-in real PostgreSQL tests. Each test uses an isolated, randomly named schema."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import create_engine, text, select, func
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import User, Subscription, CollectionJob, Paper
from app.schemas import SubscriptionInput
from app.jobs import create_job
from app.collection import save_candidate, recount
from app.providers.base import Candidate

pytestmark = pytest.mark.postgres


@pytest.fixture
def pg():
    url = os.getenv('TEST_POSTGRES_URL')
    if not url:
        pytest.skip('TEST_POSTGRES_URL missing; real PostgreSQL not verified')
    engine = create_engine(url)
    schema = 'test_' + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA {schema}'))
    isolated = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    Base.metadata.create_all(isolated)
    sessions = sessionmaker(isolated, expire_on_commit=False)
    with sessions() as db:
        user=User(email='pg@example.com',password_hash='not-used')
        db.add(user);db.flush()
        for _ in range(2):
            db.add(Subscription(user_id=user.id,**SubscriptionInput(topic='Concurrent collection').model_dump()))
        db.commit()
    yield sessions
    isolated.dispose()
    with engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
    engine.dispose()


def test_concurrent_dispatch_unique(pg):
    barrier=Barrier(2)
    def run(_):
        with pg() as db:
            barrier.wait()
            return create_job(db,1)[0].id
    with ThreadPoolExecutor(2) as pool:
        result=list(pool.map(run,range(2)))
    assert result[0]==result[1]
    with pg() as db:
        assert db.scalar(select(func.count()).select_from(CollectionJob))==1


def test_concurrent_global_doi_and_subscription_count(pg):
    with pg() as db:
        jobs=[create_job(db,id_)[0].id for id_ in (1,2)]
    barrier=Barrier(2)
    def run(id_):
        with pg() as db:
            job=db.get(CollectionJob,id_)
            barrier.wait()
            paper=save_candidate(db,job,Candidate(title='Same globally shared paper',source='arxiv',source_id='2401.12345',doi='10.1234/shared'))
            return paper.id,recount(db,job)['new_count']
    with ThreadPoolExecutor(2) as pool:
        result=list(pool.map(run,jobs))
    assert result[0]==result[1] and result[0][1]==1
    with pg() as db:
        assert db.scalar(select(func.count()).select_from(Paper))==1


def test_concurrent_summary_cache(pg,monkeypatch):
    from app.summaries import summarize_paper
    from app.schemas import SummaryData
    import time
    with pg() as db:
        job,_=create_job(db,1)
        paper=save_candidate(db,job,Candidate(title='An abstract for shared summary',source='arxiv',source_id='a',abstract='Verified abstract'))
        id_=paper.id
    class Summary:
        calls=0
        def summarize(self,p):
            self.calls+=1
            time.sleep(.1)
            return SummaryData(research_question='목적',methods=None,key_findings=[],limitations=[],takeaway=None),{}
    provider=Summary()
    barrier=Barrier(2)
    def run(_):
        with pg() as db:
            p=db.get(Paper,id_)
            barrier.wait()
            return summarize_paper(db,p,{},provider=provider).id
    with ThreadPoolExecutor(2) as pool:
        result=list(pool.map(run,range(2)))
    assert result[0]==result[1] and provider.calls==1
