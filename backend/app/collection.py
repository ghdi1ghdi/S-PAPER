import hashlib
import json
import time
from dataclasses import asdict
from datetime import datetime
from datetime import timedelta
from difflib import SequenceMatcher
from sqlalchemy import select, text as sql_text
from .config import settings
from .db import now, utc
from .models import Paper, PaperSource, SubscriptionPaper, CollectionJobPaper, Subscription
from .providers.base import Candidate, SearchPage, norm_title, ProviderError, sanitize
from .providers.enrichment import CrossrefMetadataEnricher, author_keys
from .providers.publisher import PublisherMetadataEnricher
from .providers.scholar import GoogleScholarProvider
from .providers.arxiv import ArxivProvider
from .providers.http import HTTPGateway
from .queries import build_queries
from .summaries import summarize_paper, current_summary


def storage_lock(db):
    # Serialize only short metadata/link transactions, never network calls.
    if db.bind.dialect.name == "postgresql":
        db.execute(sql_text("SELECT pg_advisory_xact_lock(810024)"))


def find_paper(db, c):
    if c.doi:
        p = db.scalar(select(Paper).where(Paper.doi == c.doi))
        if p:
            if c.source_id:
                source_paper = db.scalar(select(PaperSource).where(PaperSource.source == c.source, PaperSource.source_id == c.source_id))
                if source_paper and source_paper.paper_id != p.id:
                    # Do not silently reassign source IDs or lose existing discovery history.
                    raise ProviderError("IDENTITY_CONFLICT_REVIEW_REQUIRED")
            return p
    source = None
    if c.source_id:
        source = db.scalar(select(PaperSource).where(PaperSource.source == c.source, PaperSource.source_id == c.source_id))
    if source is None:
        source = db.scalar(select(PaperSource).where(PaperSource.source == c.source, PaperSource.fingerprint == c.fingerprint()))
    if source:
        p = db.get(Paper, source.paper_id)
        if c.doi and p.doi and c.doi != p.doi:
            raise ProviderError("CONFLICTING_DOI")
        return p
    if c.publication_year is None or not c.authors:
        return None
    # Bound candidates by confirmed year; never substitute year=0.
    for p in db.scalars(select(Paper).where(Paper.publication_year == c.publication_year)):
        if c.doi and p.doi and c.doi != p.doi:
            continue
        sources = set(db.scalars(select(PaperSource.source).where(PaperSource.paper_id == p.id)))
        if c.source not in sources:
            continue  # Preprint/publication merging requires an explicit ID (usually DOI).
        a, b = norm_title(c.title), p.normalized_title
        author_match = bool(author_keys(c.authors) & author_keys(p.authors))
        journal_match = bool(c.journal and p.journal and norm_title(c.journal) == norm_title(p.journal))
        if a == b and author_match and (len(a.split()) >= 5 or journal_match):
            return p
        if len(a.split()) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.97 and author_match and journal_match:
            return p
    return None


def save_candidate(db, job, c, allow_new=True):
    storage_lock(db)
    paper = find_paper(db, c)
    inserted, enriched = paper is None, False
    existing_link = db.get(SubscriptionPaper, (job.subscription_id, paper.id)) if paper else None
    if not allow_new and not existing_link:
        db.rollback()
        return None
    if paper is None:
        paper = Paper(title=c.title, normalized_title=norm_title(c.title), authors=c.authors,
            journal=c.journal, issns=c.issns, publication_year=c.publication_year, published_at=c.published_at,
            date_precision=c.date_precision, doi=c.doi, abstract=c.abstract, search_snippet=c.search_snippet,
            provenance=c.provenance)
        db.add(paper)
        db.flush()
    else:
        provenance = dict(paper.provenance)
        for field in ("authors", "journal", "issns", "publication_year", "published_at", "date_precision", "doi", "abstract", "search_snippet"):
            value = getattr(c, field)
            # Prefer confirmed journal publication date over preprint submission date.
            prefer = field in ("publication_year", "published_at", "date_precision") and c.provenance.get("publication_year", {}).get("source") == "crossref" and provenance.get("publication_year", {}).get("source") == "arxiv"
            if value and (not getattr(paper, field) or prefer):
                setattr(paper, field, value)
                if field in c.provenance:
                    provenance[field] = c.provenance[field]
                enriched = True
        paper.provenance = provenance
    source = db.scalar(select(PaperSource).where(PaperSource.source == c.source,
        PaperSource.source_id == c.source_id)) if c.source_id else db.scalar(select(PaperSource).where(
            PaperSource.source == c.source, PaperSource.fingerprint == c.fingerprint()))
    if source is None:
        db.add(PaperSource(paper_id=paper.id, source=c.source, source_id=c.source_id, source_version=c.source_version,
            fingerprint=c.fingerprint(), source_url=c.source_url, raw_metadata=sanitize(c.raw)))
    else:
        history = list(source.raw_metadata.get("observations", []))
        observation = {"version": source.source_version, "metadata": {k: v for k, v in source.raw_metadata.items() if k != "observations"}}
        if source.source_version != c.source_version:
            history.append(observation)
        source.raw_metadata = sanitize(c.raw) | {"observations": history}
        if c.source == "arxiv" and c.abstract and c.source_version and source.source_version and int(c.source_version[1:]) > int(source.source_version[1:]) and paper.provenance.get("abstract", {}).get("source") == "arxiv":
            paper.abstract = c.abstract
            paper.provenance = dict(paper.provenance) | {"abstract": c.provenance.get("abstract", {})}
            enriched = True
        source.source_version, source.retrieved_at = c.source_version, now()
    prior = db.get(CollectionJobPaper, (job.id, paper.id))
    if existing_link is None:
        db.add(SubscriptionPaper(subscription_id=job.subscription_id, paper_id=paper.id, first_job_id=job.id))
    if prior is None:
        db.add(CollectionJobPaper(job_id=job.id, paper_id=paper.id, outcome="duplicate" if existing_link else "new",
                                  inserted=inserted, enriched=enriched))
    elif enriched:
        prior.enriched = True
    paper.abstract_digest = hashlib.sha256((paper.abstract or "").encode()).hexdigest()
    db.commit()
    return paper


def recount(db, job):
    rows = list(db.scalars(select(CollectionJobPaper).where(CollectionJobPaper.job_id == job.id)))
    counts = dict(job.counts)
    counts.update(new_count=sum(r.outcome == "new" for r in rows), duplicate_count=sum(r.outcome == "duplicate" for r in rows),
                  global_inserted_count=sum(r.inserted for r in rows), enriched_count=sum(r.enriched for r in rows),
                  summarized_count=sum(bool((s := current_summary(db, db.get(Paper, r.paper_id))) and s.status == "success") for r in rows))
    job.counts = counts
    db.commit()
    return counts


class CollectionService:
    def __init__(self, db, job, providers=None, enrichers=None, summary_provider=None, gateway=None):
        self.db, self.job = db, job
        self.cfg = settings()
        elapsed = (now() - utc(job.started_at)).total_seconds() if job.started_at else 0
        self.deadline = time.monotonic() + max(0, self.cfg.max_job_seconds - elapsed)
        self.usage = dict(job.usage)
        self.http = gateway or HTTPGateway(self.usage, self.deadline, on_usage=self.persist_usage)
        self.providers = providers if providers is not None else [GoogleScholarProvider(self.http), ArxivProvider(self.http)]
        self.enrichers = enrichers if enrichers is not None else [PublisherMetadataEnricher(self.cfg.publisher_allowed_hosts), CrossrefMetadataEnricher(self.http)]
        self.summary_provider = summary_provider
        self.warnings = list(job.warnings)

    def persist_usage(self):
        self.job.usage = json.loads(json.dumps(self.usage))
        self.job.heartbeat_at = now()
        self.db.commit()

    def run(self):
        db, job = self.db, self.job
        snapshot = job.snapshot
        queries = build_queries(snapshot["topic"], snapshot["keywords"], snapshot.get("queries"))
        sub = db.get(Subscription, job.subscription_id)
        options = dict(snapshot.get("search_options", {}))
        search_key = hashlib.sha256(json.dumps([queries, options], sort_keys=True).encode()).hexdigest()
        last_state = sub.search_state.get(search_key, {})
        options["recent"] = options.get("sort", "auto") == "recent" or (options.get("sort", "auto") == "auto" and bool(last_state))
        if options["recent"] and last_state.get("completed_at"):
            options["date_from"] = (utc(now()) - timedelta(days=options.get("overlap_days", 30))).strftime("%Y%m%d")
        if job.queries:
            queries, options = job.queries["queries"], job.queries["options"]
            search_key = job.queries["search_state_key"]
        job.queries = {"queries": queries, "options": options, "search_state_key": search_key}
        job.status, job.started_at, job.heartbeat_at = "running", job.started_at or now(), now()
        db.commit()
        states = dict(job.provider_states)
        buffers = {}
        providers = sorted([p for p in self.providers if p.name in snapshot["enabled_sources"]], key=lambda p: p.name != "google_scholar")
        goal = snapshot["papers_per_cycle"]
        counts = recount(db, job)
        # Recover summaries of committed papers even when the search target was already reached.
        for row in db.scalars(select(CollectionJobPaper).where(CollectionJobPaper.job_id == job.id)):
            paper = db.get(Paper, row.paper_id)
            summary = current_summary(db, paper)
            if time.monotonic() < self.deadline and (summary is None or summary.status in ("pending", "running")):
                result = summarize_paper(db, paper, self.usage.setdefault("llm", {}), provider=self.summary_provider, before_call=self.persist_usage)
                if result.status in ("failed", "configuration_error", "pending"):
                    self.warnings.append("summary:" + (result.error or result.status))

        def fetch(p, offset):
            state = states.setdefault(p.name, {"pages": 0, "offsets": [], "fingerprints": [], "status": "pending"})
            if state["pages"] >= self.cfg.max_search_pages_per_source:
                state.update(status="partial", reason="PAGE_BUDGET", next_offset=None)
                self.warnings.append(f"{p.name}:PAGE_BUDGET")
                return None
            try:
                if time.monotonic() >= self.deadline:
                    raise ProviderError("TIME_BUDGET")
                page = p.search(queries[p.name], offset, options)
                signature = hashlib.sha256(json.dumps([c.fingerprint() for c in page.candidates]).encode()).hexdigest()
                if offset in state["offsets"] or (page.candidates and signature in state["fingerprints"]):
                    raise ProviderError("REPEATED_PAGE")
                state["pages"] += 1
                state["offsets"].append(offset)
                state["fingerprints"].append(signature)
                state.update(status="success", next_offset=page.next_offset if page.candidates else None)
                job.counts = dict(job.counts) | {"fetched_count": job.counts.get("fetched_count", 0) + page.fetched_count}
                self.warnings.extend(f"{p.name}:{w}" for w in page.warnings)
                # Mark current page unconsumed. A crash re-fetches it and reuses durable discovery rows.
                state["pending_offset"] = offset
                # Durable normalized page buffer: a crash never re-fetches a completed HTTP page.
                serialized = [{k: v.isoformat() if isinstance(v, datetime) else v for k, v in asdict(c).items()} for c in page.candidates]
                job.checkpoint = dict(job.checkpoint) | {p.name: {"candidates": serialized,
                    "next_offset": page.next_offset, "fetched_count": page.fetched_count, "warnings": page.warnings}}
                return page
            except ProviderError as exc:
                state.update(status="failed", reason=exc.code, next_offset=None)
                self.warnings.append(f"{p.name}:{exc.code}")
                return None
            finally:
                job.provider_states = json.loads(json.dumps(states))
                self.persist_usage()

        # Independently request each enabled first page before selecting Scholar-first candidates.
        for p in providers:
            state = states.get(p.name, {})
            if p.name in job.checkpoint:
                stored = job.checkpoint[p.name]
                candidates = []
                for data in stored["candidates"]:
                    data = dict(data)
                    if data.get("published_at"):
                        data["published_at"] = datetime.fromisoformat(data["published_at"])
                    candidates.append(Candidate(**data))
                buffers[p.name] = SearchPage(candidates, stored["next_offset"], stored["fetched_count"], stored["warnings"])
                continue
            if counts["new_count"] >= goal:
                continue
            if state.get("pages"):
                offset = state.get("next_offset")
                if offset is None:
                    continue
            else:
                offset = 0
            buffers[p.name] = fetch(p, offset)
        for p in providers:
            page = buffers.get(p.name)
            while page:
                for candidate in page.candidates:
                    if time.monotonic() >= self.deadline:
                        self.warnings.append("TIME_BUDGET")
                        break
                    try:
                        quick = find_paper(db, candidate)
                        if counts["new_count"] >= goal and not (quick and db.get(SubscriptionPaper, (sub.id, quick.id))):
                            continue
                        if not quick or not quick.abstract or not quick.doi:
                            for enricher in self.enrichers:
                                try:
                                    candidate = enricher.enrich(candidate)
                                except ProviderError as exc:
                                    self.warnings.append(f"metadata:{exc.code}")
                                except Exception:
                                    self.warnings.append("metadata:UPSTREAM_ERROR")
                        paper = save_candidate(db, job, candidate, counts["new_count"] < goal)
                        if paper:
                            llm = self.usage.setdefault("llm", {})
                            record = summarize_paper(db, paper, llm, provider=self.summary_provider, before_call=self.persist_usage) if time.monotonic() < self.deadline else None
                            if record is None:
                                self.warnings.append("summary:TIME_BUDGET")
                            elif record.status in ("failed", "configuration_error", "pending"):
                                self.warnings.append("summary:" + (record.error or record.status))
                            self.persist_usage()
                        counts = recount(db, job)
                    except ProviderError as exc:
                        db.rollback()
                        self.warnings.append(exc.code)
                job.checkpoint = {k: v for k, v in job.checkpoint.items() if k != p.name}
                states[p.name].pop("pending_offset", None)
                job.provider_states = json.loads(json.dumps(states))
                job.warnings = list(dict.fromkeys(self.warnings))
                db.commit()
                offset = states[p.name].get("next_offset")
                if counts["new_count"] >= goal or offset is None or not page.candidates or time.monotonic() >= self.deadline:
                    break
                page = fetch(p, offset)
        counts = recount(db, job)
        all_failed = bool(states) and all(s["status"] == "failed" for s in states.values())
        job.warnings = list(dict.fromkeys(self.warnings))
        if all_failed and not counts["new_count"] and not counts["duplicate_count"]:
            job.status, job.stop_reason = "failed", "all_sources_failed"
        elif job.warnings:
            job.status = "partial"
            job.stop_reason = "target_reached_with_warnings" if counts["new_count"] >= goal else "partial_results"
        else:
            job.status = "success"
            job.stop_reason = "target_reached" if counts["new_count"] >= goal else "no_new_results" if counts["new_count"] == 0 else "results_exhausted"
        job.finished_at, job.heartbeat_at = now(), now()
        if not all_failed:
            sub.search_state = sub.search_state | {search_key: {"completed_at": now().isoformat(), "job_id": job.id}}
        self.persist_usage()
        self.http.close()
        return job
