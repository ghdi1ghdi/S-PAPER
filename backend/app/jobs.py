from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import now, utc
from .models import Subscription, CollectionJob
from .scheduling import next_run


def subscription_snapshot(sub):
    return {key: getattr(sub, key) for key in ("topic", "keywords", "enabled_sources", "queries", "schedule", "timezone", "papers_per_cycle", "search_options")}


def create_job(db, subscription_id, scheduled_for=None):
    sub = db.scalar(select(Subscription).where(Subscription.id == subscription_id).with_for_update())
    active = db.scalar(select(CollectionJob).where(CollectionJob.subscription_id == sub.id, CollectionJob.status.in_(["queued", "running"])))
    if active:
        db.commit()
        return active, False
    scheduled_for = scheduled_for or now()
    existing = db.scalar(select(CollectionJob).where(CollectionJob.subscription_id == sub.id, CollectionJob.scheduled_for == scheduled_for))
    if existing:
        db.commit()
        return existing, False
    job = CollectionJob(subscription_id=sub.id, scheduled_for=scheduled_for, snapshot=subscription_snapshot(sub))
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        job = db.scalar(select(CollectionJob).where(CollectionJob.subscription_id == sub.id).order_by(CollectionJob.id.desc()))
        return job, False
    return job, True


def dispatch_due(db, at=None):
    at = at or now()
    ids = list(db.scalars(select(Subscription.id).where(Subscription.is_active.is_(True),
        Subscription.deleted_at.is_(None), Subscription.next_run_at <= at)))
    for id_ in ids:
        sub = db.scalar(select(Subscription).where(Subscription.id == id_).with_for_update())
        if not sub.is_active or not sub.next_run_at or utc(sub.next_run_at) > at:
            db.commit()
            continue
        scheduled_for = sub.next_run_at
        # Advance and insert the outbox row in one transaction. One catch-up, never all missed cycles.
        sub.next_run_at = next_run(sub.schedule, sub.timezone, at, sub.created_at)
        create_job(db, sub.id, scheduled_for)
