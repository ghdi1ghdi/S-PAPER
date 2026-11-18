'use client';
import { useCallback, useEffect, useState } from 'react';
import type { Job, Paper, Subscription, User } from './types';
import { api, sourceName, stamp, statusName } from './lib';
import { Badge, Empty, Icon, Modal } from './components/ui';
import { SubscriptionForm } from './components/SubscriptionForm';
import { JobCard } from './components/JobCard';
import { PaperCard, PaperDetail } from './components/Papers';

type Dashboard = { total_papers: number; recent_new: number; active_jobs: number; problem_jobs: number; next_run_at: string | null };
const TABS: { key: string; title: string; icon: string; sub: string }[] = [
  { key: 'dashboard', title: '연구 대시보드', icon: 'home', sub: '수집 현황을 한눈에' },
  { key: 'subscriptions', title: '수집 설정', icon: 'radar', sub: '주제와 일정 관리' },
  { key: 'papers', title: '누적 논문', icon: 'library', sub: '모은 논문과 AI 요약' },
  { key: 'jobs', title: '실행 이력', icon: 'history', sub: '각 회차의 결과와 경고' },
  { key: 'admin', title: '관리자', icon: 'shield', sub: '연결 상태와 IF 데이터' },
];
const DEFAULT_FILTERS = { sort: 'collected_desc' };

function Login({ onLogin, error, busy }: { onLogin: (form: FormData) => void; error: string; busy: boolean }) {
  return (
    <main className="login">
      <section className="login-art" aria-hidden="true">
        <div className="brand light">
          S-PAPER<small>RESEARCH LIBRARY</small>
        </div>
        <blockquote>
          매일 아침,
          <br />
          내 연구 주제의 새 논문이
          <br />
          요약되어 기다립니다.
        </blockquote>
        <ul className="login-points">
          <li>Google Scholar · arXiv 자동 수집</li>
          <li>OpenAlex · Crossref · Europe PMC 초록 보완</li>
          <li>주제 관련도 순 정렬과 한국어 AI 요약</li>
        </ul>
      </section>
      <form
        className="login-form"
        onSubmit={(e) => {
          e.preventDefault();
          onLogin(new FormData(e.currentTarget));
        }}
      >
        <div className="brand">
          S-PAPER<small>RESEARCH LIBRARY</small>
        </div>
        <h1>연구를 이어가세요.</h1>
        <p className="muted">주제별 논문과 초록 기반 AI 요약을 한곳에.</p>
        {error && (
          <div className="alert error" role="alert">
            {error}
          </div>
        )}
        <label>
          이메일
          <input name="email" type="email" autoComplete="username" required />
        </label>
        <label>
          비밀번호
          <input name="password" type="password" autoComplete="current-password" required />
        </label>
        <button className="primary block" disabled={busy}>
          {busy ? '로그인 중…' : '로그인'}
        </button>
        <p className="muted small">계정은 관리자 CLI에서 생성합니다.</p>
      </form>
    </main>
  );
}

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [tab, setTab] = useState('dashboard');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobTotal, setJobTotal] = useState(0);
  const [jobPage, setJobPage] = useState(1);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [providers, setProviders] = useState<Record<string, boolean | string>>({});
  const [filters, setFilters] = useState<Record<string, string>>(DEFAULT_FILTERS);
  const [draftFilters, setDraftFilters] = useState<Record<string, string>>(DEFAULT_FILTERS);
  const [editor, setEditor] = useState<Subscription | null | undefined>(undefined);
  const [detail, setDetail] = useState<Paper | null>(null);
  const closeEditor = useCallback(() => setEditor(undefined), []);
  const closeDetail = useCallback(() => setDetail(null), []);
  const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v)).toString();

  const load = useCallback(async () => {
    if (!user) return;
    try {
      const [s, j, d, p, pr] = await Promise.all([
        api<Subscription[]>('/subscriptions'),
        api<{ items: Job[]; total: number }>(`/jobs?page=${jobPage}`),
        api<Dashboard>('/dashboard'),
        api<{ items: Paper[]; total: number }>(`/papers?${query}&page=${page}`),
        api<Record<string, boolean | string>>('/providers'),
      ]);
      setSubs(s);
      setJobs(j.items);
      setJobTotal(j.total);
      setDashboard(d);
      setPapers(p.items);
      setTotal(p.total);
      setProviders(pr);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [user, page, query, jobPage]);

  useEffect(() => {
    api<User>('/auth/me')
      .then(setUser)
      .catch(() => {})
      .finally(() => setChecking(false));
  }, []);
  useEffect(() => {
    if (!user) return;
    void load();
    const id = setInterval(() => void load(), 5000);
    return () => clearInterval(id);
  }, [load, user]);

  async function action(fn: () => Promise<unknown>) {
    setBusy(true);
    setError('');
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const showPaper = (id: number) => void action(async () => setDetail(await api<Paper>(`/papers/${id}`)));

  if (checking)
    return (
      <div className="splash" role="status">
        연결 확인 중…
      </div>
    );
  if (!user)
    return (
      <Login
        error={error}
        busy={busy}
        onLogin={(form) =>
          void action(async () =>
            setUser(await api<User>('/auth/login', { method: 'POST', body: JSON.stringify(Object.fromEntries(form)) })),
          )
        }
      />
    );

  const tabs = TABS.filter((t) => t.key !== 'admin' || user.is_admin);
  const current = TABS.find((t) => t.key === tab)!;
  const running = jobs.filter((j) => j.status === 'running' || j.status === 'queued').length;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          S-PAPER<small>RESEARCH LIBRARY</small>
        </div>
        <nav className="nav" aria-label="주 메뉴">
          {tabs.map((t) => (
            <button key={t.key} className={tab === t.key ? 'active' : ''} aria-current={tab === t.key ? 'page' : undefined} onClick={() => setTab(t.key)}>
              <Icon name={t.icon} />
              <span>{t.title}</span>
              {t.key === 'jobs' && running > 0 && <span className="nav-pill">{running}</span>}
            </button>
          ))}
        </nav>
        <div className="side-bottom">
          <span className="user-email">{user.email}</span>
          <button
            className="ghost small"
            onClick={() =>
              void action(async () => {
                await api('/auth/logout', { method: 'POST' });
                setUser(null);
              })
            }
          >
            <Icon name="logout" size={15} /> 로그아웃
          </button>
        </div>
      </aside>

      <main className="main">
        <header className="page-head">
          <div>
            <div className="eyebrow">{current.sub}</div>
            <h1>{current.title}</h1>
          </div>
          <div className="head-actions">
            {tab === 'papers' ? (
              <>
                <a className="button-link ghost" href="/api/papers/export.csv">
                  <Icon name="download" size={15} />
                  누적 전체 CSV
                </a>
                <a className="button-link" href={'/api/papers/export.csv?' + query}>
                  <Icon name="download" size={15} />
                  필터 결과 CSV
                </a>
              </>
            ) : (
              <button className="primary" onClick={() => setEditor(null)}>
                + 수집 설정
              </button>
            )}
          </div>
        </header>

        {providers.demo_mode && <div className="alert warn">데모 데이터</div>}
        {error && (
          <div className="alert error" role="alert">
            <span>{error}</span>
            <button onClick={() => setError('')} className="ghost small">
              닫기
            </button>
          </div>
        )}
        {notice && (
          <div className="alert info" role="status">
            {notice}
          </div>
        )}
        {(!providers.google_scholar || !providers.llm) && (
          <div className="alert warn">
            {!providers.google_scholar && 'Google Scholar 연결 설정 필요. '}
            {!providers.llm && 'AI 요약 키·모델 설정 필요. '}
            확보된 논문 조회와 CSV 다운로드는 계속 사용할 수 있습니다.
          </div>
        )}

        {tab === 'dashboard' && (
          <>
            <section className="stats">
              {(
                [
                  ['누적 논문', dashboard?.total_papers, 'library'],
                  ['최근 30회 신규', dashboard?.recent_new, 'sparkle'],
                  ['실행·대기 중', dashboard?.active_jobs, 'play'],
                  ['최근 실패·부분 성공', dashboard?.problem_jobs, 'history'],
                ] as [string, number | undefined, string][]
              ).map(([name, value, icon]) => (
                <div className="stat" key={name}>
                  <span className="stat-icon">
                    <Icon name={icon} />
                  </span>
                  <span className="stat-label">{name}</span>
                  <strong>{value?.toLocaleString() ?? '—'}</strong>
                </div>
              ))}
            </section>
            <section className="next-run">
              <div>
                <span className="eyebrow">다음 수집</span>
                <h2>{stamp(dashboard?.next_run_at || null)}</h2>
                <p className="muted small">Asia/Seoul</p>
              </div>
              <button className="ghost" onClick={() => setTab('subscriptions')}>
                일정 관리
              </button>
            </section>
            <div className="section-head">
              <h2>최근 실행</h2>
              <button className="ghost small" onClick={() => setTab('jobs')}>
                모두 보기
              </button>
            </div>
            {jobs.length ? (
              <div className="job-grid">
                {jobs.slice(0, 3).map((j) => (
                  <JobCard key={j.id} job={j} />
                ))}
              </div>
            ) : (
              <div className="card">
                <Empty title="첫 연구 주제를 등록하세요.">수집 설정을 만든 뒤 지금 수집을 실행할 수 있습니다.</Empty>
              </div>
            )}
          </>
        )}

        {tab === 'subscriptions' && (
          <div className="sub-grid">
            {subs.length === 0 && (
              <div className="card">
                <Empty title="등록된 수집 설정이 없습니다." />
              </div>
            )}
            {subs.map((s) => (
              <article className={'sub-card' + (s.is_active ? '' : ' paused')} key={s.id}>
                <div className="sub-head">
                  <h2>{s.topic}</h2>
                  <span className={'pill ' + (s.is_active ? 'on' : 'off')}>{s.is_active ? '활성' : '일시정지'}</span>
                </div>
                {s.keywords.length > 0 && (
                  <div className="paper-tags">
                    {s.keywords.map((k) => (
                      <span className="tag subtle" key={k}>
                        {k}
                      </span>
                    ))}
                  </div>
                )}
                <dl className="sub-meta">
                  <div>
                    <dt>검색원</dt>
                    <dd>{s.enabled_sources.map(sourceName).join(' · ')}</dd>
                  </div>
                  <div>
                    <dt>회당 목표</dt>
                    <dd>{s.papers_per_cycle}편</dd>
                  </div>
                  <div>
                    <dt>다음 실행</dt>
                    <dd>
                      {stamp(s.next_run_at, s.timezone)} <span className="muted">· {s.timezone}</span>
                    </dd>
                  </div>
                  {s.last_job && (
                    <div>
                      <dt>마지막 결과</dt>
                      <dd>
                        <Badge value={s.last_job.status} /> 신규 {s.last_job.counts.new_count || 0} / {s.last_job.snapshot.papers_per_cycle}편
                      </dd>
                    </div>
                  )}
                </dl>
                <details>
                  <summary>실제 검색어</summary>
                  {Object.entries(s.effective_queries).map(([k, v]) => (
                    <div className="preview-row" key={k}>
                      <span className="eyebrow">{sourceName(k)}</span>
                      <code className="code">{v}</code>
                    </div>
                  ))}
                </details>
                <div className="sub-actions">
                  <div className="row">
                    <button
                      disabled={busy}
                      className="primary"
                      onClick={() =>
                        void action(async () => {
                          const r = await api<{ message: string }>(`/subscriptions/${s.id}/run-now`, { method: 'POST' });
                          setNotice(r.message);
                          setTab('jobs');
                        })
                      }
                    >
                      지금 수집
                    </button>
                    <button className="ghost" onClick={() => setEditor(s)}>
                      수정
                    </button>
                    <button
                      className="ghost"
                      disabled={busy}
                      onClick={() => void action(() => api(`/subscriptions/${s.id}/${s.is_active ? 'pause' : 'resume'}`, { method: 'POST' }))}
                    >
                      {s.is_active ? '일시정지' : '재개'}
                    </button>
                  </div>
                  <button
                    className="danger-link"
                    onClick={() => {
                      if (confirm('수집 설정을 삭제할까요? 누적 논문은 유지됩니다.')) void action(() => api(`/subscriptions/${s.id}`, { method: 'DELETE' }));
                    }}
                  >
                    삭제
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}

        {tab === 'papers' && (
          <div className="library">
            <form
              className="filter-bar"
              onSubmit={(e) => {
                e.preventDefault();
                setFilters(draftFilters);
                setPage(1);
              }}
            >
              <div className="filter-search">
                <label>
                  제목
                  <input
                    value={draftFilters.title || ''}
                    placeholder="제목으로 검색"
                    onChange={(e) => setDraftFilters({ ...draftFilters, title: e.target.value })}
                  />
                </label>
                <label>
                  정렬
                  <select value={draftFilters.sort} onChange={(e) => setDraftFilters({ ...draftFilters, sort: e.target.value })}>
                    <option value="collected_desc">최근 수집순</option>
                    <option value="relevance_desc">관련도순</option>
                    <option value="year_desc">최신 발표년도순</option>
                    <option value="collected_asc">오래된 수집순</option>
                    <option value="title">제목순</option>
                  </select>
                </label>
              </div>
              <details className="filter-more">
                <summary>상세 필터</summary>
                <div className="filters">
                  <label>
                    저널
                    <input value={draftFilters.journal || ''} onChange={(e) => setDraftFilters({ ...draftFilters, journal: e.target.value })} />
                  </label>
                  <label>
                    발표년도
                    <input type="number" value={draftFilters.year || ''} onChange={(e) => setDraftFilters({ ...draftFilters, year: e.target.value })} />
                  </label>
                  <label>
                    출처
                    <select value={draftFilters.source || ''} onChange={(e) => setDraftFilters({ ...draftFilters, source: e.target.value })}>
                      <option value="">전체</option>
                      <option value="google_scholar">Google Scholar</option>
                      <option value="arxiv">arXiv</option>
                      <option value="both">Google Scholar + arXiv</option>
                    </select>
                  </label>
                  <label>
                    수집 설정
                    <select
                      value={draftFilters.subscription_id || ''}
                      onChange={(e) => setDraftFilters({ ...draftFilters, subscription_id: e.target.value })}
                    >
                      <option value="">전체</option>
                      {subs.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.topic}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    요약 상태
                    <select
                      value={draftFilters.summary_status || ''}
                      onChange={(e) => setDraftFilters({ ...draftFilters, summary_status: e.target.value })}
                    >
                      <option value="">전체</option>
                      {['success', 'pending', 'failed', 'configuration_error', 'skipped_no_abstract', 'retry_queued'].map((s) => (
                        <option key={s} value={s}>
                          {statusName[s]}
                        </option>
                      ))}
                    </select>
                  </label>
                  {(
                    [
                      ['collected_from', '수집 시작일'],
                      ['collected_to', '수집 종료일'],
                    ] as const
                  ).map(([k, label]) => (
                    <label key={k}>
                      {label}
                      <input
                        type="date"
                        value={(draftFilters[k] || '').slice(0, 10)}
                        onChange={(e) =>
                          setDraftFilters({
                            ...draftFilters,
                            [k]: e.target.value ? e.target.value + (k === 'collected_to' ? 'T23:59:59+09:00' : 'T00:00:00+09:00') : '',
                          })
                        }
                      />
                    </label>
                  ))}
                </div>
              </details>
              <div className="filter-actions">
                <span className="muted">총 {total.toLocaleString()}편</span>
                <div className="row">
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => {
                      setDraftFilters(DEFAULT_FILTERS);
                      setFilters(DEFAULT_FILTERS);
                      setPage(1);
                    }}
                  >
                    초기화
                  </button>
                  <button className="primary">필터 적용</button>
                </div>
              </div>
            </form>

            {papers.length ? (
              <div className="paper-list">
                {papers.map((p) => (
                  <PaperCard key={p.id} paper={p} open={showPaper} />
                ))}
              </div>
            ) : (
              <div className="card">
                <Empty title="표시할 논문이 없습니다.">수집을 실행하거나 필터를 조정하세요.</Empty>
              </div>
            )}
            <div className="pager">
              <button className="ghost" disabled={page === 1} onClick={() => setPage(page - 1)}>
                이전
              </button>
              <span className="muted">
                {page} / {Math.max(1, Math.ceil(total / 20))} 페이지
              </span>
              <button className="ghost" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>
                다음
              </button>
            </div>
            <p className="muted small">
              관련도는 주제·키워드가 제목과 초록에 얼마나 나타나는지로 계산합니다. IF는 저장된 검증 데이터의 최신 기준 연도입니다. CSV는 정확히 7열이며 미확보
              값은 빈 셀, IF 0은 0으로 내보냅니다.
            </p>
          </div>
        )}

        {tab === 'jobs' && (
          <>
            {jobs.length ? (
              <div className="job-list">
                {jobs.map((j) => (
                  <JobCard key={j.id} job={j} details />
                ))}
              </div>
            ) : (
              <div className="card">
                <Empty title="실행 이력이 없습니다." />
              </div>
            )}
            <div className="pager">
              <button className="ghost" disabled={jobPage === 1} onClick={() => setJobPage(jobPage - 1)}>
                이전
              </button>
              <span className="muted">
                {jobPage} / {Math.max(1, Math.ceil(jobTotal / 30))}
              </span>
              <button className="ghost" disabled={jobPage * 30 >= jobTotal} onClick={() => setJobPage(jobPage + 1)}>
                다음
              </button>
            </div>
          </>
        )}

        {tab === 'admin' && (
          <div className="admin-grid">
            <section className="card">
              <h2>연결 설정 상태</h2>
              <ul className="status-list">
                {Object.entries(providers)
                  .filter(([k]) => k !== 'demo_mode')
                  .map(([k, v]) => (
                    <li key={k}>
                      <span>{sourceName(k)}</span>
                      <span className={'pill ' + (v === false ? 'off' : 'on')}>{typeof v === 'boolean' ? (v ? '설정됨' : '설정 필요') : v}</span>
                    </li>
                  ))}
              </ul>
              <p className="muted small">API 키는 서버 환경변수에서 설정하며 화면에 표시하지 않습니다.</p>
            </section>
            <form
              className="card form"
              onSubmit={(e) => {
                e.preventDefault();
                const data = new FormData(e.currentTarget);
                void action(async () => {
                  const result = await api<{ imported: number; errors: { row: number; error: string }[] }>('/admin/if/import', {
                    method: 'POST',
                    body: data,
                  });
                  setNotice(
                    result.errors.length ? result.errors.map((x) => `${x.row}행: ${x.error}`).join(' · ') : `${result.imported}행 IF 데이터 가져오기 완료`,
                  );
                });
              }}
            >
              <h2>검증된 IF CSV 가져오기</h2>
              <p className="muted small">
                사용 권한이 있는 Journal Impact Factor 데이터만 업로드하세요. ISSN/eISSN으로 매칭하며, 오류 행이 있으면 전체 가져오기를 취소합니다.
              </p>
              <code className="code">journal_name,issn,eissn,metric_year,impact_factor,source_name,source_reference,verified_at</code>
              <label>
                IF CSV 파일
                <input name="file" type="file" accept=".csv,text/csv" required />
              </label>
              <button disabled={busy} className="primary">
                검증 및 가져오기
              </button>
            </form>
          </div>
        )}

        <footer className="footer">초록 기반 AI 요약 · 발표년도는 확인된 저널 게재연도, 없으면 arXiv 최초 제출연도 · 화면 기본 시간대 Asia/Seoul</footer>
      </main>

      {editor !== undefined && (
        <Modal title={editor ? '수집 설정 수정' : '새 수집 설정'} close={closeEditor}>
          <SubscriptionForm
            initial={editor}
            onDone={() => {
              setEditor(undefined);
              setTab('subscriptions');
              void load();
            }}
          />
        </Modal>
      )}
      {detail && (
        <Modal title="논문 상세" close={closeDetail}>
          <PaperDetail
            paper={detail}
            busy={busy}
            retry={() =>
              void action(async () => {
                await api(`/papers/${detail.id}/summary/retry`, { method: 'POST' });
                setDetail(await api<Paper>(`/papers/${detail.id}`));
                setNotice('요약 재시도를 요청했습니다.');
              })
            }
          />
        </Modal>
      )}
    </div>
  );
}
