'use client';
import type { Job } from '../types';
import { reasonName, sourceName, stamp, statusName } from '../lib';
import { Badge } from './ui';

export function JobCard({ job, details = false }: { job: Job; details?: boolean }) {
  const count = job.counts.new_count || 0;
  const goal = job.snapshot.papers_per_cycle;
  const pct = Math.min(100, (count / goal) * 100);
  const stats: [string, number][] = [
    ['조회', job.counts.fetched_count || 0],
    ['관련도 미달 제외', job.counts.filtered_count || 0],
    ['기존 중복', job.counts.duplicate_count || 0],
    ['메타데이터 보완', job.counts.enriched_count || 0],
    ['요약', job.counts.summarized_count || 0],
  ];
  return (
    <article className={'job-card ' + job.status}>
      <div className="job-head">
        <div>
          <h3>
            {job.snapshot.topic} <span className="muted">#{job.id}</span>
          </h3>
          <span className="muted small">{stamp(job.scheduled_for)}</span>
        </div>
        <Badge value={job.status} />
      </div>
      <div className="job-progress">
        <div className="job-count">
          <strong>{count}</strong>
          <span>/ {goal}편 신규</span>
        </div>
        {job.stop_reason && <span className="job-reason">{reasonName[job.stop_reason] || job.stop_reason}</span>}
      </div>
      <div className="progress" role="progressbar" aria-valuenow={count} aria-valuemin={0} aria-valuemax={goal}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <dl className="job-stats">
        {stats.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {details && (
        <>
          <div className="paper-tags">
            {Object.entries(job.provider_states).map(([name, s]) => (
              <span key={name} className="tag">
                {sourceName(name)} · {statusName[s.status] || s.status} · {s.pages || 0}페이지 {s.reason || ''}
              </span>
            ))}
          </div>
          {job.warnings.length > 0 && <div className="alert warn">{job.warnings.join(' · ')}</div>}
          <details>
            <summary>요청·재시도·캐시·토큰 사용량 및 실제 검색어</summary>
            <pre>{JSON.stringify({ usage: job.usage, queries: job.queries }, null, 2)}</pre>
            <p className="muted small">HTTP 요청 수는 확정 과금 횟수가 아닙니다.</p>
          </details>
        </>
      )}
    </article>
  );
}
