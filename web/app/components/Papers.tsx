'use client';
import type { Paper } from '../types';
import { provenanceSource, sourceName, stamp } from '../lib';
import { Badge, Icon, RelevanceMeter } from './ui';

const doiUrl = (doi: string) => 'https://doi.org/' + encodeURIComponent(doi);

function Byline({ paper }: { paper: Paper }) {
  const authors = paper.authors.length > 3 ? paper.authors.slice(0, 3).join(', ') + ' 외' : paper.authors.join(', ');
  return (
    <p className="byline">
      {authors || '저자 정보 없음'}
      {paper.journal && (
        <>
          <span className="dot" aria-hidden="true">·</span>
          <em>{paper.journal}</em>
        </>
      )}
      {paper.publication_year && (
        <>
          <span className="dot" aria-hidden="true">·</span>
          {paper.publication_year}
        </>
      )}
    </p>
  );
}

export function PaperCard({ paper, open }: { paper: Paper; open: (id: number) => void }) {
  const abstractFrom = provenanceSource(paper.provenance, 'abstract');
  const preview = paper.ai_summary || paper.abstract;
  return (
    <article className="paper-card">
      <div className="paper-main">
        <h3 className="paper-title">
          <button onClick={() => open(paper.id)}>{paper.title}</button>
        </h3>
        <Byline paper={paper} />
        {preview ? (
          <p className={'paper-preview' + (paper.ai_summary ? ' is-summary' : '')}>
            {paper.ai_summary && (
              <span className="preview-tag">
                <Icon name="sparkle" size={13} /> AI 요약
              </span>
            )}
            {preview.replace(/\n/g, ' ')}
          </p>
        ) : (
          <p className="paper-preview missing">초록을 찾지 못해 요약하지 않았습니다.</p>
        )}
        <div className="paper-tags">
          {paper.sources.map((s) => (
            <span className="tag" key={s}>
              {sourceName(s)}
            </span>
          ))}
          {abstractFrom && !paper.sources.includes(abstractFrom) && <span className="tag subtle">초록 · {sourceName(abstractFrom)}</span>}
          {paper.journal_impact_factor !== null && <span className="tag accent">IF {paper.journal_impact_factor}</span>}
          {paper.doi ? (
            <a className="tag link" href={doiUrl(paper.doi)} target="_blank" rel="noreferrer">
              DOI ↗
            </a>
          ) : (
            <span className="tag muted">DOI 없음</span>
          )}
          <Badge value={paper.summary_status} />
        </div>
      </div>
      <aside className="paper-side">
        <RelevanceMeter score={paper.relevance} />
        <span className="collected">{stamp(paper.collected_at)}</span>
      </aside>
    </article>
  );
}

function SummaryBody({ text }: { text: string | null }) {
  if (!text) return <div className="prose">아직 요약이 없습니다.</div>;
  // ai_summary is "라벨: 내용" per line (SummaryData.readable on the server).
  const lines = text.split('\n').filter(Boolean);
  const takeaway = lines.find((l) => l.startsWith('핵심:'));
  return (
    <div className="summary-body">
      {takeaway && <p className="takeaway">{takeaway.replace(/^핵심:\s*/, '')}</p>}
      {lines
        .filter((l) => l !== takeaway)
        .map((line, i) => {
          const m = line.match(/^([^:]{1,12}):\s*(.*)$/);
          return m ? (
            <p key={i} className="summary-line">
              <strong>{m[1]}:</strong> {m[2]}
            </p>
          ) : (
            <p key={i} className="summary-line">
              {line}
            </p>
          );
        })}
    </div>
  );
}

export function PaperDetail({ paper, busy, retry }: { paper: Paper; busy: boolean; retry: () => void }) {
  const abstractFrom = provenanceSource(paper.provenance, 'abstract');
  return (
    <div className="detail">
      <header className="detail-hero">
        <div className="paper-tags">
          {paper.sources.map((s) => (
            <span className="tag" key={s}>
              {sourceName(s)}
            </span>
          ))}
          <RelevanceMeter score={paper.relevance} />
        </div>
        <h1 className="detail-title">{paper.title}</h1>
        <p className="byline">{paper.authors.join(', ') || '저자 정보 없음'}</p>
        <div className="link-row">
          {paper.doi && (
            <a className="button-link" href={doiUrl(paper.doi)} target="_blank" rel="noreferrer">
              DOI: {paper.doi} <Icon name="external" size={14} />
            </a>
          )}
          {paper.source_links.map((s, i) =>
            s.url ? (
              <a key={i} className="button-link ghost" href={s.url} target="_blank" rel="noreferrer">
                {sourceName(s.source)} {s.version} <Icon name="external" size={14} />
              </a>
            ) : null,
          )}
        </div>
      </header>

      <dl className="facts">
        <div>
          <dt>저널</dt>
          <dd>{paper.journal || '정보 없음'}</dd>
        </div>
        <div>
          <dt>발표년도</dt>
          <dd>
            {paper.publication_year || '정보 없음'}
            {paper.date_precision && <span className="muted"> · {paper.date_precision}</span>}
          </dd>
        </div>
        <div>
          <dt>저널 Impact Factor</dt>
          <dd>
            {paper.if_metric ? (
              <>
                <strong>{paper.if_metric.value}</strong> <span className="muted">· {paper.if_metric.year}년 기준</span>
              </>
            ) : (
              '정보 없음'
            )}
          </dd>
        </div>
        <div>
          <dt>수집일</dt>
          <dd>{stamp(paper.collected_at)}</dd>
        </div>
      </dl>

      <section className="detail-section summary-section">
        <div className="section-head">
          <h2>
            <Icon name="sparkle" /> 초록 기반 AI 요약
          </h2>
          <Badge value={paper.summary_status} />
        </div>
        <SummaryBody text={paper.ai_summary} />
        {paper.summary_error && <p className="muted small">오류 코드: {paper.summary_error}</p>}
        <button className="ghost" disabled={!paper.abstract || busy} onClick={retry}>
          요약 재시도
        </button>
      </section>

      <section className="detail-section">
        <div className="section-head">
          <h2>원문 초록</h2>
          {abstractFrom && <span className="tag subtle">출처 · {sourceName(abstractFrom)}</span>}
        </div>
        <div className="prose">{paper.abstract || '정보 없음'}</div>
        {paper.search_snippet && (
          <details>
            <summary>검색 미리보기 · 초록 아님</summary>
            <p className="prose">{paper.search_snippet}</p>
          </details>
        )}
        <details>
          <summary>초록 및 서지정보 출처·매칭 근거</summary>
          <pre>{JSON.stringify(paper.provenance, null, 2)}</pre>
        </details>
        {paper.if_metric && (
          <p className="muted small">
            IF: {paper.if_metric.journal} · {paper.if_metric.source} · {paper.if_metric.reference} · 검증 {stamp(paper.if_metric.verified_at)}
          </p>
        )}
      </section>
    </div>
  );
}
