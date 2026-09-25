from datetime import datetime
from sqlalchemy import String, Text, JSON, ForeignKey, UniqueConstraint, Index, CheckConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, now


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (CheckConstraint("papers_per_cycle BETWEEN 1 AND 100"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    topic: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSON)
    enabled_sources: Mapped[list] = mapped_column(JSON)
    queries: Mapped[dict] = mapped_column(JSON, default=dict)
    schedule: Mapped[dict] = mapped_column(JSON)
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Seoul")
    papers_per_cycle: Mapped[int] = mapped_column(default=10)
    is_active: Mapped[bool] = mapped_column(default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    search_options: Mapped[dict] = mapped_column(JSON, default=dict)
    search_state: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Paper(Base):
    __tablename__ = "papers"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text, index=True)
    authors: Mapped[list] = mapped_column(JSON, default=list)
    journal: Mapped[str | None] = mapped_column(Text)
    issns: Mapped[list] = mapped_column(JSON, default=list)
    publication_year: Mapped[int | None] = mapped_column(index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_precision: Mapped[str | None] = mapped_column(String(20))
    doi: Mapped[str | None] = mapped_column(Text, unique=True)
    abstract: Mapped[str | None] = mapped_column(Text)
    search_snippet: Mapped[str | None] = mapped_column(Text)
    abstract_digest: Mapped[str] = mapped_column(String(64), default="")
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    first_collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class PaperSource(Base):
    __tablename__ = "paper_sources"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_source_identity"),
                     UniqueConstraint("source", "fingerprint", name="uq_source_fingerprint"))
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    source: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[str | None] = mapped_column(Text)
    source_version: Mapped[str | None] = mapped_column(String(20))
    fingerprint: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_metadata: Mapped[dict] = mapped_column(JSON)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CollectionJob(Base):
    __tablename__ = "collection_jobs"
    __table_args__ = (UniqueConstraint("subscription_id", "scheduled_for", name="uq_job_cycle"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    queries: Mapped[dict] = mapped_column(JSON, default=dict)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    provider_states: Mapped[dict] = mapped_column(JSON, default=dict)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    stop_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SubscriptionPaper(Base):
    __tablename__ = "subscription_papers"
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), primary_key=True)
    first_job_id: Mapped[int] = mapped_column(ForeignKey("collection_jobs.id"))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class CollectionJobPaper(Base):
    __tablename__ = "collection_job_papers"
    job_id: Mapped[int] = mapped_column(ForeignKey("collection_jobs.id"), primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), primary_key=True)
    outcome: Mapped[str] = mapped_column(String(20))
    inserted: Mapped[bool] = mapped_column(default=False)
    enriched: Mapped[bool] = mapped_column(default=False)


class PaperSummary(Base):
    __tablename__ = "paper_summaries"
    __table_args__ = (UniqueConstraint("paper_id", "provider", "model", "language", "abstract_hash", "prompt_version",
                                      name="uq_summary_input"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(120))
    language: Mapped[str] = mapped_column(String(10), default="ko")
    abstract_hash: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(20))
    summary_json: Mapped[dict | None] = mapped_column(JSON)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    token_usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class JournalMetric(Base):
    __tablename__ = "journal_metrics"
    __table_args__ = (UniqueConstraint("identity", "metric_year", name="uq_metric_identity_year"),
                     CheckConstraint("impact_factor >= 0"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    identity: Mapped[str] = mapped_column(String(300))
    journal_name: Mapped[str] = mapped_column(Text)
    issn: Mapped[str | None] = mapped_column(String(9), index=True)
    eissn: Mapped[str | None] = mapped_column(String(9), index=True)
    metric_year: Mapped[int]
    impact_factor: Mapped[float]
    source_name: Mapped[str] = mapped_column(Text)
    source_reference: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# A partial index guarantees only one active job, including racing manual/scheduled requests.
Index("uq_active_subscription_job", CollectionJob.subscription_id, unique=True,
      postgresql_where=CollectionJob.status.in_(["queued", "running"]),
      sqlite_where=CollectionJob.status.in_(["queued", "running"]))
