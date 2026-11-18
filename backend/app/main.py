import hashlib
import logging
from datetime import datetime
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Query
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError
import redis
from .config import settings
from .db import get_db, SessionLocal, now
from .models import LoginSession, Subscription, CollectionJob, Paper, PaperSummary
from .auth import user_required, admin_required, login, token_hash
from .schemas import SubscriptionInput
from .scheduling import next_run
from .queries import build_queries
from .jobs import create_job
from .papers import paper_query, paper_dto, csv_rows
from .summaries import current_summary, abstract_hash, PROMPT_VERSION
from .metrics import import_metrics

# Never log HTTPX request URLs: SerpApi credentials are query parameters.
for name in ("httpx", "httpcore", "openai", "google.genai"):
    logging.getLogger(name).setLevel(logging.CRITICAL)
# Interactive API docs expose every route and schema; keep them off unless explicitly enabled.
_docs = settings().api_docs
app = FastAPI(title="S-PAPER", version="0.1.0", docs_url="/docs" if _docs else None,
              redoc_url="/redoc" if _docs else None, openapi_url="/openapi.json" if _docs else None)


@app.middleware("http")
async def security(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("origin") != settings().app_origin or request.headers.get("x-requested-with") != "S-PAPER":
            return JSONResponse({"detail": "요청 출처를 확인할 수 없습니다"}, 403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


@app.post("/auth/login")
def auth_login(payload: LoginInput, request: Request, response: Response, db=Depends(get_db)):
    # Redis-backed per-account rate limiting also works behind the same-origin web proxy.
    key = "login:" + hashlib.sha256(payload.email.lower().encode()).hexdigest()
    cache = redis.Redis.from_url(settings().redis_url)
    try:
        attempts = cache.incr(key)
        if attempts == 1:
            cache.expire(key, 900)
        if attempts > 15:
            raise HTTPException(429, "로그인 시도가 많습니다. 15분 후 다시 시도하세요")
    except redis.RedisError:
        raise HTTPException(503, "세션 보호 서비스 연결 실패") from None
    user, token = login(db, str(payload.email), payload.password)
    cache.delete(key)
    response.set_cookie("session", token, httponly=True, secure=settings().cookie_secure,
        samesite="lax", max_age=settings().session_hours * 3600, path="/")
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}


@app.post("/auth/logout")
def auth_logout(request: Request, response: Response, db=Depends(get_db)):
    token = request.cookies.get("session")
    session = db.get(LoginSession, token_hash(token)) if token else None
    if session:
        db.delete(session)
        db.commit()
    response.delete_cookie("session", path="/")
    return {"ok": True}


@app.get("/auth/me")
def me(user=Depends(user_required)):
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}


def owned_subscription(db, id_, user):
    sub = db.get(Subscription, id_)
    if not sub or sub.user_id != user.id or sub.deleted_at:
        raise HTTPException(404, "수집 설정을 찾을 수 없습니다")
    return sub


def job_dto(job):
    return {k: getattr(job, k) for k in ("id", "subscription_id", "scheduled_for", "status", "snapshot", "queries",
        "counts", "usage", "provider_states", "warnings", "stop_reason", "started_at", "finished_at", "created_at")}


def sub_dto(db, sub):
    last = db.scalar(select(CollectionJob).where(CollectionJob.subscription_id == sub.id).order_by(CollectionJob.id.desc()).limit(1))
    return {k: getattr(sub, k) for k in ("id", "topic", "keywords", "enabled_sources", "queries", "schedule", "timezone",
        "papers_per_cycle", "is_active", "next_run_at", "search_options")} | {
        "effective_queries": build_queries(sub.topic, sub.keywords, sub.queries), "last_job": job_dto(last) if last else None}


@app.post("/subscriptions/query-preview")
def query_preview(payload: SubscriptionInput, user=Depends(user_required)):
    return build_queries(payload.topic, payload.keywords, payload.queries)


@app.get("/subscriptions")
def subscriptions(user=Depends(user_required), db=Depends(get_db)):
    return [sub_dto(db, sub) for sub in db.scalars(select(Subscription).where(Subscription.user_id == user.id,
        Subscription.deleted_at.is_(None)).order_by(Subscription.id.desc()))]


@app.post("/subscriptions", status_code=201)
def create_subscription(payload: SubscriptionInput, user=Depends(user_required), db=Depends(get_db)):
    sub = Subscription(user_id=user.id, **payload.model_dump())
    sub.next_run_at = next_run(payload.schedule.model_dump(), payload.timezone, now())
    db.add(sub)
    db.commit()
    return sub_dto(db, sub)


@app.get("/subscriptions/{id_}")
def get_subscription(id_: int, user=Depends(user_required), db=Depends(get_db)):
    return sub_dto(db, owned_subscription(db, id_, user))


@app.put("/subscriptions/{id_}")
def update_subscription(id_: int, payload: SubscriptionInput, user=Depends(user_required), db=Depends(get_db)):
    sub = owned_subscription(db, id_, user)
    for k, v in payload.model_dump().items():
        setattr(sub, k, v)
    sub.next_run_at = next_run(sub.schedule, sub.timezone, now(), sub.created_at) if sub.is_active else None
    db.commit()
    return sub_dto(db, sub)


@app.delete("/subscriptions/{id_}")
def delete_subscription(id_: int, user=Depends(user_required), db=Depends(get_db)):
    sub = owned_subscription(db, id_, user)
    sub.is_active, sub.next_run_at, sub.deleted_at = False, None, now()
    db.commit()
    return {"ok": True, "message": "설정은 보관 처리되며 누적 논문은 유지됩니다"}


@app.post("/subscriptions/{id_}/{action}")
def subscription_action(id_: int, action: Literal["pause", "resume", "run-now"], user=Depends(user_required), db=Depends(get_db)):
    sub = owned_subscription(db, id_, user)
    if action == "run-now":
        job, created = create_job(db, sub.id)
        return {"job": job_dto(job), "created": created, "message": "수집 대기 중" if created else "이미 실행 중인 작업입니다"}
    sub.is_active = action == "resume"
    sub.next_run_at = next_run(sub.schedule, sub.timezone, now(), sub.created_at) if sub.is_active else None
    db.commit()
    return sub_dto(db, sub)


def filters(title: str = "", journal: str = "", year: int | None = Query(None, ge=1500, le=2200),
    source: Literal["", "google_scholar", "arxiv", "both"] = "", subscription_id: int | None = None,
    collected_from: datetime | None = None, collected_to: datetime | None = None,
    summary_status: Literal["", "pending", "success", "failed", "configuration_error", "skipped_no_abstract", "retry_queued", "running"] = "",
    sort: Literal["collected_desc", "collected_asc", "title", "year_desc", "relevance_desc"] = "collected_desc"):
    return locals()


@app.get("/papers")
def papers(f: dict = Depends(filters), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    user=Depends(user_required), db=Depends(get_db)):
    query = paper_query(user.id, f)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    return {"items": [paper_dto(db, p, user.id) for p in db.scalars(query.offset((page-1)*page_size).limit(page_size))],
            "total": total, "page": page, "page_size": page_size}


@app.get("/papers/export.csv")
def export(f: dict = Depends(filters), user=Depends(user_required)):
    def stream():
        with SessionLocal() as db:
            yield from csv_rows(db, user.id, f)
    filename = now().strftime("papers_%Y%m%d_%H%M.csv")
    return StreamingResponse(stream(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def owned_paper(db, id_, user):
    p = db.scalar(paper_query(user.id, {}).where(Paper.id == id_))
    if not p:
        raise HTTPException(404, "논문을 찾을 수 없습니다")
    return p


@app.get("/papers/{id_}")
def paper_detail(id_: int, user=Depends(user_required), db=Depends(get_db)):
    return paper_dto(db, owned_paper(db, id_, user), user.id)


@app.post("/papers/{id_}/summary/retry")
def summary_retry(id_: int, user=Depends(user_required), db=Depends(get_db)):
    paper = owned_paper(db, id_, user)
    if not paper.abstract:
        return {"status": "skipped_no_abstract"}
    record = current_summary(db, paper)
    if record and record.status in ("running", "retry_queued"):
        return {"status": record.status}
    if record is None:
        cfg = settings()
        record = PaperSummary(paper_id=paper.id, provider=cfg.llm_provider, model=getattr(cfg, f"{cfg.llm_provider}_model", ""),
            abstract_hash=abstract_hash(paper), prompt_version=PROMPT_VERSION)
        db.add(record)
    record.status, record.error = "retry_queued", None
    db.commit()
    return {"status": "retry_queued"}


@app.get("/jobs")
def jobs(user=Depends(user_required), db=Depends(get_db), page: int = Query(1, ge=1)):
    query = select(CollectionJob).join(Subscription).where(Subscription.user_id == user.id)
    return {"items": [job_dto(j) for j in db.scalars(query.order_by(CollectionJob.id.desc()).offset((page-1)*30).limit(30))],
            "total": db.scalar(select(func.count()).select_from(query.subquery()))}


@app.get("/jobs/{id_}")
def job_detail(id_: int, user=Depends(user_required), db=Depends(get_db)):
    job = db.scalar(select(CollectionJob).join(Subscription).where(CollectionJob.id == id_, Subscription.user_id == user.id))
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다")
    return job_dto(job)


@app.get("/dashboard")
def dashboard(user=Depends(user_required), db=Depends(get_db)):
    query = select(CollectionJob).join(Subscription).where(Subscription.user_id == user.id)
    recent = list(db.scalars(query.order_by(CollectionJob.id.desc()).limit(30)))
    return {"total_papers": db.scalar(select(func.count()).select_from(paper_query(user.id, {}).order_by(None).subquery())),
        "recent_new": sum(j.counts.get("new_count", 0) for j in recent),
        "active_jobs": db.scalar(select(func.count()).select_from(query.where(CollectionJob.status.in_(["queued", "running"])).subquery())),
        "problem_jobs": sum(j.status in ("failed", "partial") for j in recent),
        "next_run_at": db.scalar(select(func.min(Subscription.next_run_at)).where(Subscription.user_id == user.id,
            Subscription.is_active.is_(True), Subscription.deleted_at.is_(None)))}


@app.get("/providers")
def providers(user=Depends(user_required)):
    return settings().provider_status()


@app.post("/admin/if/import")
async def if_import(file: UploadFile = File(...), user=Depends(admin_required), db=Depends(get_db)):
    content = await file.read(10_000_001)
    if len(content) > 10_000_000:
        raise HTTPException(413, "CSV 최대 10MB")
    try:
        return import_metrics(db, content.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise HTTPException(422, "UTF-8 CSV를 사용하세요") from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "동시에 가져온 데이터와 중복됩니다") from None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready(db=Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        redis.Redis.from_url(settings().redis_url).ping()
        token_hash("readiness")
        return {"status": "ready"}
    except Exception:
        return JSONResponse({"status": "not_ready"}, 503)
