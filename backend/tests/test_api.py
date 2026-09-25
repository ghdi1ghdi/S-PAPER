import csv
import io
from datetime import datetime, timezone
import pytest
from app.auth import hasher
from app.models import User, Paper, JournalMetric
from app.collection import save_candidate
from app.providers.base import Candidate
from app.metrics import import_metrics, ImportedJournalMetricProvider
from app.papers import csv_rows, HEADERS
from app.scheduling import next_run
from app.summaries import summarize_paper
from app.schemas import SummaryData


def signin(client):
    response=client.post('/auth/login',json={'email':'researcher@example.com','password':'test-password-123'})
    assert response.status_code==200
    assert 'HttpOnly' in response.headers['set-cookie']


def test_auth_ownership_and_csv(client,db,user,job):
    save_candidate(db,job,Candidate(title='Private paper',source='arxiv',source_id='2401.12345'))
    assert client.get('/papers').status_code==401
    signin(client)
    assert client.get('/papers').json()['total']==1
    p=client.get('/papers').json()['items'][0]
    assert set(['title','journal','journal_impact_factor','publication_year','doi','abstract','ai_summary','sources','source_links','collected_at']).issubset(p)
    response=client.get('/papers/export.csv')
    assert response.content.startswith(b'\xef\xbb\xbf')
    assert list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))[0]==HEADERS
    client.post('/auth/logout')
    other=User(email='other@example.com',password_hash=hasher.hash('test-password-123'))
    db.add(other);db.commit()
    assert client.post('/auth/login',json={'email':other.email,'password':'test-password-123'}).status_code==200
    assert client.get('/papers').json()['total']==0
    assert client.get(f'/papers/{p["id"]}').status_code==404
    assert client.get(f'/jobs/{job.id}').status_code==404
    assert client.post(f'/subscriptions/{job.subscription_id}/run-now').status_code==404
    assert len(list(csv.reader(io.StringIO(client.get('/papers/export.csv').content.decode('utf-8-sig')))))==1
    assert client.post('/admin/if/import',files={'file':('x.csv',b'bad','text/csv')}).status_code==403


def test_csrf_and_validations(client,user):
    assert client.post('/auth/login',headers={'Origin':'https://evil.example'},json={'email':user.email,'password':'test-password-123'}).status_code==403
    signin(client)
    assert client.post('/subscriptions',json={'topic':'x','papers_per_cycle':101}).status_code==422
    assert client.post('/subscriptions',json={'topic':'x','timezone':'Bad/Zone'}).status_code==422
    created=client.post('/subscriptions',json={'topic':'EEG brain age','keywords':['EEG','brain age']})
    assert created.status_code==201
    id_=created.json()['id']
    assert client.post(f'/subscriptions/{id_}/pause').json()['next_run_at'] is None
    assert client.post(f'/subscriptions/{id_}/resume').json()['next_run_at']
    a=client.post(f'/subscriptions/{id_}/run-now').json()
    b=client.post(f'/subscriptions/{id_}/run-now').json()
    assert a['created'] and not b['created'] and a['job']['id']==b['job']['id']
    assert 'api_key' not in client.get('/providers').text


def test_csv_null_zero_injection_unicode(db,user,job):
    p=save_candidate(db,job,Candidate(title='=한글,"따옴표"\n두 줄',source='arxiv',source_id='a',issns=['1234-5679'],abstract='초록, 줄\n둘'))
    db.add(JournalMetric(identity='1234-5679',journal_name='Journal',issn='1234-5679',metric_year=2024,impact_factor=0,source_name='licensed',source_reference='ref',verified_at=datetime(2025,1,1,tzinfo=timezone.utc)))
    db.commit()
    content=''.join(csv_rows(db,user.id,{}))
    rows=list(csv.reader(io.StringIO(content.lstrip('\ufeff'))))
    assert rows[0]==HEADERS and len(rows[1])==7
    assert rows[1][0]=='\'=한글,"따옴표"\n두 줄' and rows[1][2]=='0' and rows[1][3]==''
    assert rows[1][5]=='초록, 줄\n둘'
    metric=ImportedJournalMetricProvider(db).lookup(p)
    assert metric.metric_year==2024 and metric.source_name=='licensed'


def test_if_atomic_import_validation(db):
    header='journal_name,issn,eissn,metric_year,impact_factor,source_name,source_reference,verified_at\n'
    row='Journal,1234-5679,,2024,0,licensed,ref,2025-01-01T00:00:00Z\n'
    result=import_metrics(db,header+row+'Other,bad,,2024,-1,x,ref,2025-01-01T00:00:00Z\n')
    assert result['imported']==0 and result['errors'][0]['row']==3
    assert import_metrics(db,header+row)['imported']==1
    assert import_metrics(db,header+row)['errors'][0]['row']==2


@pytest.mark.parametrize('schedule,tz,after,expected',[
    ({'kind':'daily','time':'09:00'},'Asia/Seoul','2025-01-01T23:00:00+00:00','2025-01-02T00:00:00+00:00'),
    ({'kind':'weekly','time':'09:00','weekday':0},'Asia/Seoul','2025-01-06T00:00:00+00:00','2025-01-13T00:00:00+00:00'),
    ({'kind':'hours','interval':6},'Asia/Seoul','2025-01-01T00:00:00+00:00','2025-01-01T06:00:00+00:00'),
    ({'kind':'daily','time':'02:30'},'America/New_York','2025-03-09T05:00:00+00:00','2025-03-09T07:30:00+00:00')])
def test_next_run(schedule,tz,after,expected):
    assert next_run(schedule,tz,datetime.fromisoformat(after)).isoformat()==expected


class Summary:
    calls=0
    def summarize(self,p):
        self.calls+=1
        return SummaryData(research_question='연구 목적.',methods=None,key_findings=['결과.'],limitations=[],takeaway=None),{'input_tokens':10}


def test_summary_no_abstract_cache_and_failure(db,job):
    p=save_candidate(db,job,Candidate(title='Paper',source='arxiv',source_id='a'))
    provider=Summary()
    assert summarize_paper(db,p,{},provider=provider).status=='skipped_no_abstract'
    assert provider.calls==0
    p.abstract='A verified abstract';db.commit()
    a=summarize_paper(db,p,{},provider=provider)
    b=summarize_paper(db,p,{},provider=provider)
    assert a.id==b.id and provider.calls==1 and a.ai_summary=='연구 목적: 연구 목적.\n결과: 결과.'
    class Broken:
        def summarize(self,p):
            raise TimeoutError('secret')
    failed=summarize_paper(db,p,{},force=True,provider=Broken())
    assert failed.status=='failed' and failed.error=='TimeoutError'
    assert db.get(Paper,p.id).abstract


def test_summary_budget_leaves_pending(db,job,monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings(),'llm_max_calls_per_job',0)
    p=save_candidate(db,job,Candidate(title='Paper',source='arxiv',source_id='a',abstract='Abstract'))
    assert summarize_paper(db,p,{},provider=Summary()).status=='pending'


def test_csv_all_pages_and_subscription_dedup(db,user,job,sub):
    from app.models import Subscription
    from app.jobs import subscription_snapshot, create_job
    for i in range(25):
        save_candidate(db,job,Candidate(title=f'논문 {i}',source='arxiv',source_id=str(i)))
    job.status='success';db.commit()
    other=Subscription(user_id=user.id,**subscription_snapshot(sub))
    db.add(other);db.commit()
    second,_=create_job(db,other.id)
    save_candidate(db,second,Candidate(title='논문 0',source='arxiv',source_id='0'))
    rows=list(csv.reader(io.StringIO(''.join(csv_rows(db,user.id,{})).lstrip('\ufeff'))))
    assert len(rows)==26
    filtered=list(csv.reader(io.StringIO(''.join(csv_rows(db,user.id,{'title':'논문 24'})).lstrip('\ufeff'))))
    assert len(filtered)==2 and filtered[1][0]=='논문 24'
