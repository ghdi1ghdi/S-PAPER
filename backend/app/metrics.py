import csv
import io
import math
import re
from datetime import datetime, timezone
from sqlalchemy import select, or_
from .models import JournalMetric
from .providers.base import norm_title


def validate_issn(value):
    if not value:
        return None
    v = value.strip().upper()
    if not re.fullmatch(r"\d{4}-\d{3}[\dX]", v):
        raise ValueError("ISSN 형식 오류")
    digits = v.replace("-", "")
    checksum = sum(int(digits[i]) * (8 - i) for i in range(7)) + (10 if digits[7] == "X" else int(digits[7]))
    if checksum % 11:
        raise ValueError("ISSN 체크섬 오류")
    return v


def import_metrics(db, content):
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    fields = {"journal_name", "issn", "eissn", "metric_year", "impact_factor", "source_name", "source_reference", "verified_at"}
    if not fields.issubset(reader.fieldnames or []):
        return {"imported": 0, "errors": [{"row": 1, "error": "필수 헤더 누락"}]}
    errors, rows, seen = [], [], set()
    for line, row in enumerate(reader, 2):
        try:
            if line > 50002:
                raise ValueError("최대 50,000행")
            name, source, ref = (row[x].strip() for x in ("journal_name", "source_name", "source_reference"))
            if not all((name, source, ref)):
                raise ValueError("저널명과 출처 필수")
            issn, eissn = validate_issn(row["issn"]), validate_issn(row["eissn"])
            year, value = int(row["metric_year"]), float(row["impact_factor"])
            if not 1900 <= year <= datetime.now().year or not math.isfinite(value) or value < 0:
                raise ValueError("IF 연도/값 오류")
            verified = datetime.fromisoformat(row["verified_at"].replace("Z", "+00:00"))
            if verified.tzinfo is None or verified > datetime.now(timezone.utc):
                raise ValueError("검증 시각은 시간대 포함, 미래 시각 불가")
            identity = issn or eissn or "name:" + norm_title(name)
            key = (identity, year)
            if key in seen or db.scalar(select(JournalMetric.id).where(JournalMetric.identity == identity, JournalMetric.metric_year == year)):
                raise ValueError("중복 저널/연도")
            identifiers = set(filter(None, [issn, eissn]))
            if identifiers and (any(identifiers & set(filter(None, [r.issn, r.eissn])) and r.metric_year == year for r in rows)
                or db.scalar(select(JournalMetric.id).where(JournalMetric.metric_year == year,
                    or_(JournalMetric.issn.in_(identifiers), JournalMetric.eissn.in_(identifiers))))):
                raise ValueError("중복 ISSN/연도")
            seen.add(key)
            rows.append(JournalMetric(identity=identity, journal_name=name, issn=issn, eissn=eissn,
                metric_year=year, impact_factor=value, source_name=source, source_reference=ref, verified_at=verified))
        except (ValueError, TypeError, AttributeError) as exc:
            errors.append({"row": line, "error": str(exc)})
    if errors:
        return {"imported": 0, "errors": errors}  # Atomic import: correct every invalid row first.
    db.add_all(rows)
    db.commit()
    return {"imported": len(rows), "errors": []}


class ImportedJournalMetricProvider:
    def __init__(self, db):
        self.db = db

    def lookup(self, paper):
        if not paper.issns:
            return None  # Even similar journal names are deliberately insufficient.
        return self.db.scalar(select(JournalMetric).where(or_(JournalMetric.issn.in_(paper.issns),
            JournalMetric.eissn.in_(paper.issns))).order_by(JournalMetric.metric_year.desc(), JournalMetric.id.desc()).limit(1))
