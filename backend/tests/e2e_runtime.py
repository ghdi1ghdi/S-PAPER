"""Explicit test-only worker entrypoint. Real DB/Celery/API; external services use isolated fixtures.
Never imported by app.*, Docker Compose production services or DEMO_MODE.
"""
import json
from pathlib import Path
import httpx
from sqlalchemy import select
from app import tasks
from app.db import SessionLocal
from app.models import User
from app.auth import hasher
from app.collection import CollectionService
from app.providers.http import HTTPGateway
from app.providers.scholar import GoogleScholarProvider
from app.providers.arxiv import ArxivProvider
from app.providers.enrichment import CrossrefMetadataEnricher
from app.schemas import SummaryData

FIXTURES=Path(__file__).parent/'fixtures'


def transport(request):
    if request.url.host=='serpapi.com':
        data=json.loads((FIXTURES/'scholar.json').read_text())
        data.pop('serpapi_pagination',None)
        return httpx.Response(200,json=data)
    if request.url.host=='export.arxiv.org':
        return httpx.Response(200,text=(FIXTURES/'arxiv.xml').read_text(),headers={'Content-Type':'application/atom+xml'})
    if request.url.host=='api.crossref.org':
        return httpx.Response(200,json={'message':{'items':[]}})
    raise AssertionError('Test attempted an unexpected external host')


class FixtureSummary:
    def summarize(self,paper):
        return SummaryData(research_question='HERA 충돌에서 다중 전자 생성을 연구한다.',methods='H1 검출기를 사용했다.',key_findings=[],limitations=[],takeaway=None),{'input_tokens':10,'output_tokens':20}


class FixtureCollectionService(CollectionService):
    def __init__(self,db,job):
        gateway=HTTPGateway(usage=dict(job.usage),client=httpx.Client(transport=httpx.MockTransport(transport)))
        super().__init__(db,job,providers=[GoogleScholarProvider(gateway),ArxivProvider(gateway)],
            enrichers=[CrossrefMetadataEnricher(gateway)],summary_provider=FixtureSummary(),gateway=gateway)
        self.usage=gateway.usage
        gateway.on_usage=self.persist_usage


if __name__=='__main__':
    import sys
    if sys.argv[1]=='seed':
        import os
        password=os.environ['E2E_PASSWORD']
        with SessionLocal() as db:
            user=db.scalar(select(User).where(User.email=='e2e@example.com'))
            if user is None:
                db.add(User(email='e2e@example.com',password_hash=hasher.hash(password),is_admin=True))
            else:
                user.password_hash=hasher.hash(password)
            db.commit()
    elif sys.argv[1]=='worker':
        tasks.CollectionService=FixtureCollectionService
        tasks.celery.worker_main(['worker','--pool=solo','--loglevel=WARNING','--without-gossip','--without-mingle','--without-heartbeat'])
