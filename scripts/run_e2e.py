"""Run test-only API/worker/Beat/Next processes against dedicated PostgreSQL and Redis.
Start isolated test containers first. External HTTP/LLM calls are fixtures only in tests.e2e_runtime.
"""
import os
import secrets
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BACKEND=ROOT/'backend'
PYTHON=BACKEND/'.venv/bin/python'
NODE=ROOT/'.tools/node-v22.23.3-darwin-arm64/bin'
ENV=os.environ.copy()
ENV.update(DATABASE_URL=os.environ.get('TEST_POSTGRES_URL','postgresql+psycopg://app:test-only-password@127.0.0.1:55432/papers'),
    REDIS_URL=os.environ.get('TEST_REDIS_URL','redis://127.0.0.1:56379/2'),APP_SECRET_KEY=secrets.token_urlsafe(48),
    APP_ORIGIN='http://localhost:3000',SERPAPI_API_KEY='fixture-only-no-network',OPENAI_API_KEY='',OPENAI_MODEL='',
    API_INTERNAL_URL='http://127.0.0.1:8000',E2E_PASSWORD=os.environ.get('E2E_PASSWORD',secrets.token_urlsafe(20)),
    DEMO_MODE='true',RUN_LIVE_API_TESTS='false',PLAYWRIGHT_BROWSERS_PATH=str(ROOT/'.tools/playwright'))
if NODE.exists():
    ENV['PATH']=str(NODE)+os.pathsep+ENV['PATH']
LOGS=ROOT/'test-results'
LOGS.mkdir(exist_ok=True)
processes=[]
handles=[]


def start(name,command,cwd):
    handle=(LOGS/f'{name}.log').open('w')
    handles.append(handle)
    process=subprocess.Popen(command,cwd=cwd,env=ENV,stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
    processes.append(process)
    return process


def wait_url(url):
    for _ in range(120):
        if any(p.poll() is not None for p in processes):
            raise RuntimeError('A server exited; see test-results/*.log')
        try:
            with urllib.request.urlopen(url,timeout=2) as response:
                if response.status==200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f'Server did not become ready: {url}')


try:
    subprocess.run([str(PYTHON),'-m','alembic','upgrade','head'],cwd=BACKEND,env=ENV,check=True)
    subprocess.run([str(PYTHON),'-m','tests.e2e_runtime','seed'],cwd=BACKEND,env=ENV,check=True)
    start('api',[str(PYTHON),'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000','--no-access-log'],BACKEND)
    start('worker',[str(PYTHON),'-m','tests.e2e_runtime','worker'],BACKEND)
    start('beat',[str(PYTHON),'-m','celery','-A','app.tasks.celery','beat','--loglevel=WARNING','--schedule',str(LOGS/'beat')],BACKEND)
    start('web',['npm','run','start'],ROOT/'web')
    wait_url('http://127.0.0.1:8000/ready')
    wait_url('http://localhost:3000')
    subprocess.run(['npm','run','test:e2e'],cwd=ROOT/'web',env=ENV,check=True)
finally:
    for process in processes:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
    for handle in handles:
        handle.close()
