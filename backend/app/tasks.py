from datetime import timedelta
from celery import Celery
from sqlalchemy import select, text
from .config import settings
from .db import SessionLocal, engine, now, utc
from .models import CollectionJob, Paper, PaperSummary
from .jobs import dispatch_due
from .collection import CollectionService, recount
from .summaries import summarize_paper

cfg = settings()
celery = Celery("s_paper", broker=cfg.redis_url, backend=cfg.redis_url)
celery.conf.update(task_acks_late=True, task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1, broker_connection_retry_on_startup=True,
    task_soft_time_limit=cfg.max_job_seconds + 60, task_time_limit=cfg.max_job_seconds + 120,
    beat_schedule={"dispatch-due": {"task": "app.tasks.tick", "schedule": 30.0}}, timezone="UTC")


@celery.task(name="app.tasks.tick")
def tick():
    with SessionLocal() as db:
        dispatch_due(db)
        for job in db.scalars(select(CollectionJob).where(CollectionJob.status.in_(["queued", "running"]))):
            # Worker lock prevents duplicate execution; stale running jobs reuse durable discovery records.
            stale = job.status == "running" and job.heartbeat_at and utc(job.heartbeat_at) < now() - timedelta(seconds=cfg.max_job_seconds + 180)
            if job.status == "queued" or stale:
                if not job.enqueued_at or utc(job.enqueued_at) < now() - timedelta(seconds=60):
                    run_collection.apply_async(args=[job.id], task_id=f"collection-{job.id}")
                    # If broker accepted then process crashes here, duplicate delivery is safe.
                    job.enqueued_at = now()
                    db.commit()
        for summary in db.scalars(select(PaperSummary).where(PaperSummary.status == "running",
                PaperSummary.created_at < now() - timedelta(seconds=cfg.max_job_seconds + 180))):
            summary.status = "retry_queued"
        db.commit()
        # Summary retry is a durable DB outbox, so broker downtime cannot lose user requests.
        for summary in db.scalars(select(PaperSummary).where(PaperSummary.status == "retry_queued")):
            retry_summary.delay(summary.paper_id)


def acquire(connection, namespace, id_):
    if connection.dialect.name == "postgresql":
        return connection.scalar(text("SELECT pg_try_advisory_lock(:ns, :id)"), {"ns": namespace, "id": id_})
    return True


def release(connection, namespace, id_):
    if connection.dialect.name == "postgresql":
        connection.execute(text("SELECT pg_advisory_unlock(:ns, :id)"), {"ns": namespace, "id": id_})
        connection.commit()


@celery.task(name="app.tasks.run_collection")
def run_collection(job_id):
    with engine.connect() as lock_connection, SessionLocal() as db:
        if not acquire(lock_connection, 810025, job_id):
            return
        try:
            job = db.get(CollectionJob, job_id)
            if not job or job.status not in ("queued", "running"):
                return
            try:
                CollectionService(db, job).run()
            except Exception as exc:
                db.rollback()
                job = db.get(CollectionJob, job_id)
                recount(db, job)
                job.status = "partial" if job.counts.get("new_count") else "failed"
                job.warnings = list(job.warnings) + [type(exc).__name__]
                job.stop_reason, job.finished_at = "worker_error", now()
                db.commit()
        finally:
            release(lock_connection, 810025, job_id)


@celery.task(name="app.tasks.retry_summary")
def retry_summary(paper_id):
    with engine.connect() as lock_connection, SessionLocal() as db:
        if not acquire(lock_connection, 810026, paper_id):
            return
        try:
            paper = db.get(Paper, paper_id)
            if paper:
                from .summaries import current_summary
                record = current_summary(db, paper)
                if record and record.status == "retry_queued":
                    summarize_paper(db, paper, {}, force=True)
        finally:
            release(lock_connection, 810026, paper_id)
