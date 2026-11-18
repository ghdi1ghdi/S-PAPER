import csv
import io
from sqlalchemy import select, func, exists
from .models import Paper, PaperSource, SubscriptionPaper, Subscription, PaperSummary
from .metrics import ImportedJournalMetricProvider
from .summaries import current_summary

HEADERS = ["제목", "저널", "저널 IF 지수", "발표년도", "DOI", "초록", "AI 논문 요약"]


def paper_query(user_id, filters):
    links = select(SubscriptionPaper.paper_id).join(Subscription).where(Subscription.user_id == user_id)
    if filters.get("subscription_id"):
        links = links.where(Subscription.id == filters["subscription_id"])
    if filters.get("collected_from"):
        links = links.where(SubscriptionPaper.discovered_at >= filters["collected_from"])
    if filters.get("collected_to"):
        links = links.where(SubscriptionPaper.discovered_at <= filters["collected_to"])
    query = select(Paper).where(Paper.id.in_(links))
    for key in ("title", "journal"):
        if filters.get(key):
            # Escape LIKE wildcard characters so search text remains literal.
            escaped = filters[key].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(getattr(Paper, key).ilike(f"%{escaped}%", escape="\\"))
    if filters.get("year"):
        query = query.where(Paper.publication_year == filters["year"])
    source = filters.get("source")
    if source:
        for s in (["google_scholar", "arxiv"] if source == "both" else [source]):
            query = query.where(exists(select(PaperSource.id).where(PaperSource.paper_id == Paper.id, PaperSource.source == s)))
    if filters.get("summary_status"):
        from .config import settings
        from .summaries import PROMPT_VERSION
        cfg = settings()
        # Paper.updated_at may also change for enrichment, so match hash in DTO; SQL uses latest matching provider/model.
        latest = select(PaperSummary.status).where(PaperSummary.paper_id == Paper.id,
            PaperSummary.provider == cfg.llm_provider, PaperSummary.model == getattr(cfg, f"{cfg.llm_provider}_model", ""),
            PaperSummary.prompt_version == PROMPT_VERSION, PaperSummary.abstract_hash == Paper.abstract_digest).order_by(PaperSummary.created_at.desc(), PaperSummary.id.desc()).limit(1).correlate(Paper).scalar_subquery()
        query = query.where(func.coalesce(latest, "pending") == filters["summary_status"])
    collected = select(func.min(SubscriptionPaper.discovered_at)).join(Subscription).where(
        SubscriptionPaper.paper_id == Paper.id, Subscription.user_id == user_id).correlate(Paper).scalar_subquery()
    relevance = select(func.max(SubscriptionPaper.relevance)).join(Subscription).where(
        SubscriptionPaper.paper_id == Paper.id, Subscription.user_id == user_id)
    if filters.get("subscription_id"):
        relevance = relevance.where(Subscription.id == filters["subscription_id"])
    relevance = relevance.correlate(Paper).scalar_subquery()
    sort = filters.get("sort", "collected_desc")
    order = {"title": Paper.title.asc(), "year_desc": Paper.publication_year.desc().nullslast(),
             "relevance_desc": relevance.desc().nullslast(),
             "collected_asc": collected.asc(), "collected_desc": collected.desc()}[sort]
    return query.order_by(order, Paper.id.asc())


def paper_dto(db, p, user_id):
    metric = ImportedJournalMetricProvider(db).lookup(p)
    summary = current_summary(db, p)
    sources = list(db.scalars(select(PaperSource).where(PaperSource.paper_id == p.id)))
    collected = db.scalar(select(func.min(SubscriptionPaper.discovered_at)).join(Subscription).where(
        SubscriptionPaper.paper_id == p.id, Subscription.user_id == user_id))
    relevance = db.scalar(select(func.max(SubscriptionPaper.relevance)).join(Subscription).where(
        SubscriptionPaper.paper_id == p.id, Subscription.user_id == user_id))
    return {"relevance": relevance,"id": p.id, "title": p.title, "journal": p.journal,
        "journal_impact_factor": metric.impact_factor if metric else None,
        "publication_year": p.publication_year, "doi": p.doi, "abstract": p.abstract,
        "ai_summary": summary.ai_summary if summary and summary.status == "success" else None,
        "summary_status": summary.status if summary else "skipped_no_abstract" if not p.abstract else "pending",
        "summary_error": summary.error if summary else None,
        "summary_json": summary.summary_json if summary and summary.status == "success" else None,
        "authors": p.authors, "issns": p.issns, "published_at": p.published_at,
        "date_precision": p.date_precision, "search_snippet": p.search_snippet,
        "sources": list(dict.fromkeys(s.source for s in sources)),
        "source_links": [{"source": s.source, "url": s.source_url, "version": s.source_version} for s in sources],
        "collected_at": collected, "provenance": p.provenance,
        "if_metric": {"value": metric.impact_factor, "year": metric.metric_year, "source": metric.source_name,
            "reference": metric.source_reference, "verified_at": metric.verified_at, "journal": metric.journal_name} if metric else None}


def csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, (float, int)):
        return f"{value:g}"
    value = str(value)
    if value.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        value = "'" + value
    return value


def csv_rows(db, user_id, filters):
    yield "\ufeff"
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(HEADERS)
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    # Server-side cursor; stable ordered query is executed once, no page-only export or offset drift.
    for paper in db.scalars(paper_query(user_id, filters).execution_options(yield_per=100)):
        dto = paper_dto(db, paper, user_id)
        writer.writerow([csv_cell(dto[k]) for k in ("title", "journal", "journal_impact_factor", "publication_year", "doi", "abstract", "ai_summary")])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
