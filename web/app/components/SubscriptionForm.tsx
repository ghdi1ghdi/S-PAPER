'use client';
import { FormEvent, useState } from 'react';
import type { Subscription } from '../types';
import { api, sourceName } from '../lib';

export function SubscriptionForm({ initial, onDone }: { initial: Subscription | null; onDone: () => void }) {
  const [topic, setTopic] = useState(initial?.topic || '');
  const [keywords, setKeywords] = useState(initial?.keywords.join(', ') || '');
  const [sources, setSources] = useState(initial?.enabled_sources || ['google_scholar', 'arxiv']);
  const [schedule, setSchedule] = useState(initial?.schedule || { kind: 'daily', time: '09:00', weekday: 0, interval: 1 });
  const [tz, setTz] = useState(initial?.timezone || 'Asia/Seoul');
  const [count, setCount] = useState(initial?.papers_per_cycle || 10);
  const [options, setOptions] = useState(
    initial?.search_options || { sort: 'auto', year_from: null, year_to: null, overlap_days: 30 },
  );
  const [queries, setQueries] = useState<Record<string, string>>(initial?.queries || {});
  const [preview, setPreview] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const payload = () => ({
    topic,
    keywords: keywords.split(',').map((x) => x.trim()).filter(Boolean),
    enabled_sources: sources,
    schedule,
    timezone: tz,
    papers_per_cycle: count,
    queries,
    search_options: options,
  });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await api(initial ? `/subscriptions/${initial.id}` : '/subscriptions', {
        method: initial ? 'PUT' : 'POST',
        body: JSON.stringify(payload()),
      });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}

      <fieldset>
        <legend>무엇을 찾을까요</legend>
        <label>
          연구 주제
          <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="EEG brain age" required maxLength={500} />
          <span className="hint">주제의 단어는 모두 포함된 논문을 찾습니다.</span>
        </label>
        <label>
          키워드 · 쉼표로 구분
          <input value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="EEG, brain age, aging" />
          <span className="hint">주제에 없는 키워드는 동의어처럼 하나만 맞아도 됩니다.</span>
        </label>
        <div className="field">
          <span className="field-label">검색원</span>
          <div className="chips">
            {['google_scholar', 'arxiv'].map((s) => (
              <label key={s} className={'chip-toggle' + (sources.includes(s) ? ' on' : '')}>
                <input
                  type="checkbox"
                  checked={sources.includes(s)}
                  onChange={(e) => setSources(e.target.checked ? [...sources, s] : sources.filter((x) => x !== s))}
                />
                {sourceName(s)}
              </label>
            ))}
          </div>
          <span className="hint">초록·DOI는 OpenAlex, Crossref, Europe PMC, Semantic Scholar에서 자동 보완합니다.</span>
        </div>
      </fieldset>

      <fieldset>
        <legend>언제, 얼마나</legend>
        <div className="grid-2">
          <label>
            수집 주기
            <select value={schedule.kind} onChange={(e) => setSchedule({ ...schedule, kind: e.target.value })}>
              <option value="daily">매일</option>
              <option value="weekly">매주</option>
              <option value="hours">N시간마다</option>
              <option value="days">N일마다</option>
            </select>
          </label>
          <label>
            회당 목표 개수
            <input type="number" min={1} max={100} value={count} onChange={(e) => setCount(Number(e.target.value))} required />
          </label>
          {['hours', 'days'].includes(schedule.kind) && (
            <label>
              간격 N
              <input
                type="number"
                min={1}
                max={365}
                value={schedule.interval}
                onChange={(e) => setSchedule({ ...schedule, interval: Number(e.target.value) })}
              />
            </label>
          )}
          {schedule.kind !== 'hours' && (
            <label>
              실행 시각
              <input type="time" value={schedule.time} onChange={(e) => setSchedule({ ...schedule, time: e.target.value })} required />
            </label>
          )}
          {schedule.kind === 'weekly' && (
            <label>
              요일
              <select value={schedule.weekday} onChange={(e) => setSchedule({ ...schedule, weekday: Number(e.target.value) })}>
                {['월', '화', '수', '목', '금', '토', '일'].map((s, i) => (
                  <option value={i} key={s}>
                    {s}요일
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            시간대
            <input value={tz} onChange={(e) => setTz(e.target.value)} list="zones" required />
            <datalist id="zones">
              <option>Asia/Seoul</option>
              <option>UTC</option>
              <option>America/New_York</option>
              <option>Europe/London</option>
            </datalist>
          </label>
        </div>
      </fieldset>

      <details className="advanced">
        <summary>고급 검색 설정</summary>
        <div className="form">
          <label>
            정렬
            <select value={options.sort} onChange={(e) => setOptions({ ...options, sort: e.target.value })}>
              <option value="auto">자동 · 처음 관련도, 이후 최근순</option>
              <option value="relevance">관련도 · 과거 논문 포함</option>
              <option value="recent">최근순</option>
            </select>
            <span className="hint">
              Scholar 최근순은 최근 1년간 추가된 논문 범위입니다. 과거 연도를 모으려면 관련도를 선택하세요.
            </span>
          </label>
          <div className="grid-2">
            <label>
              시작 연도
              <input
                type="number"
                min={1500}
                max={2200}
                value={options.year_from || ''}
                onChange={(e) => setOptions({ ...options, year_from: e.target.value ? Number(e.target.value) : null })}
              />
            </label>
            <label>
              종료 연도
              <input
                type="number"
                min={1500}
                max={2200}
                value={options.year_to || ''}
                onChange={(e) => setOptions({ ...options, year_to: e.target.value ? Number(e.target.value) : null })}
              />
            </label>
          </div>
          <label>
            arXiv 겹침 재검색 기간 · 일
            <input
              type="number"
              min={1}
              max={365}
              value={options.overlap_days}
              onChange={(e) => setOptions({ ...options, overlap_days: Number(e.target.value) })}
            />
          </label>
          {['google_scholar', 'arxiv'].map((s) => (
            <label key={s}>
              {sourceName(s)} 검색어 재정의
              <input value={queries[s] || ''} onChange={(e) => setQueries({ ...queries, [s]: e.target.value })} placeholder="비워두면 자동 생성" />
            </label>
          ))}
        </div>
      </details>

      <div className="preview">
        <button
          type="button"
          className="ghost"
          onClick={async () => {
            try {
              setPreview(await api('/subscriptions/query-preview', { method: 'POST', body: JSON.stringify(payload()) }));
              setError('');
            } catch (e) {
              setError((e as Error).message);
            }
          }}
        >
          실제 검색어 미리보기
        </button>
        {Object.entries(preview).map(([k, v]) => (
          <div key={k} className="preview-row">
            <span className="eyebrow">{sourceName(k)}</span>
            <code className="code">{v}</code>
          </div>
        ))}
      </div>

      <p className="hint">중복·관련도 미달·검색 결과 부족·호출 한도에 따라 실제 신규 개수는 목표보다 적을 수 있습니다.</p>
      <div className="form-actions">
        <button className="primary" disabled={busy || !sources.length}>
          {busy ? '저장 중…' : '수집 설정 저장'}
        </button>
      </div>
    </form>
  );
}
