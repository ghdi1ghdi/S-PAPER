"""Explicit paid smoke test; never enabled by ordinary test execution."""
import json
import secrets
from pathlib import Path
import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient
from app.config import settings
from app.db import SessionLocal, now
from app.models import User, Subscription, SubscriptionPaper, Paper
from app.auth import hasher, login
from app.schemas import SubscriptionInput
from app.jobs import create_job
from app.collection import CollectionService
from app.papers import paper_dto


@pytest.mark.live
def test_real_apis():
    cfg=settings()
    if not cfg.run_live_api_tests:
        pytest.skip('RUN_LIVE_API_TESTS is not true; paid external API smoke not executed')
    if not cfg.provider_status()['google_scholar'] or not cfg.provider_status()['llm']:
        pytest.skip('Real SERPAPI_API_KEY and selected LLM key/model are required')
    if not cfg.database_url.startswith('postgresql'):
        pytest.skip('Live persistence verification requires PostgreSQL DATABASE_URL')
    with SessionLocal() as db:
        password=secrets.token_urlsafe(24)
        user=User(email=f'live-{secrets.token_hex(8)}@example.com',password_hash=hasher.hash(password))
        db.add(user);db.flush()
        sub=Subscription(user_id=user.id,**SubscriptionInput(topic='EEG brain age',keywords=['EEG','brain age'],papers_per_cycle=10).model_dump())
        db.add(sub);db.commit()
        job,_=create_job(db,sub.id)
        CollectionService(db,job).run()
        papers=list(db.scalars(select(Paper).join(SubscriptionPaper).where(SubscriptionPaper.subscription_id==sub.id)))
        dtos=[paper_dto(db,p,user.id) for p in papers]
        report={'verified_at':now().isoformat(),'target':10,'actual_new':job.counts.get('new_count',0),
            'job_status':job.status,'provider_states':job.provider_states,'usage':job.usage,'warnings':job.warnings,
            'abstracts':sum(bool(p.abstract) for p in papers),
            'actual_summaries':sum(p['summary_status']=='success' for p in dtos),
            'summary_verification':'executed' if any(p.abstract for p in papers) else 'unverified_no_abstract',
            'csv_rows':len(dtos),'job_id':job.id}
        from app.main import app
        _,token=login(db,user.email,password)
        with TestClient(app) as client:
            client.cookies.set('session',token)
            assert client.get('/dashboard').json()['total_papers']==len(papers)
            csv=client.get('/papers/export.csv')
            assert csv.status_code==200 and csv.content.startswith(b'\xef\xbb\xbf')
        (Path(__file__).parents[2]/'docs/live-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        assert job.counts.get('new_count',0)<=10
        assert papers, 'Real APIs returned no usable papers; inspect live-report.json'
        assert job.status in ('success','partial')
        if report['abstracts']:
            assert report['actual_summaries']>0, 'Actual LLM summary was not verified'
