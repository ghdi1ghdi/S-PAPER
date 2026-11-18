export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const r = await fetch('/api' + path, {
    ...options,
    headers: {
      'X-Requested-With': 'S-PAPER',
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...options.headers,
    },
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: '서버에 연결할 수 없습니다' }));
    throw new Error(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail));
  }
  return r.json();
}

export const stamp = (v: string | null, tz = 'Asia/Seoul') =>
  v
    ? new Date(v.endsWith('Z') || /[+-]\d\d:\d\d$/.test(v) ? v : v + 'Z').toLocaleString('ko-KR', {
        timeZone: tz,
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : '—';

export const sourceName = (v: string) =>
  ({
    google_scholar: 'Google Scholar',
    arxiv: 'arXiv',
    openalex: 'OpenAlex',
    crossref: 'Crossref',
    europepmc: 'Europe PMC',
    semantic_scholar: 'Semantic Scholar',
    publisher: '출판사',
  })[v] || v;

export const statusName: Record<string, string> = {
  queued: '대기',
  running: '실행 중',
  success: '완료',
  partial: '부분 성공',
  failed: '실패',
  cancelled: '취소',
  pending: '요약 대기',
  configuration_error: '연결 설정 필요',
  skipped_no_abstract: '초록 없음',
  retry_queued: '재시도 대기',
};

export const reasonName: Record<string, string> = {
  target_reached: '목표 달성',
  target_reached_with_warnings: '목표 달성 · 경고 확인',
  no_new_results: '새로운 논문 없음',
  results_exhausted: '검색 결과 소진',
  partial_results: '일부 결과 · 경고 확인',
  all_sources_failed: '모든 검색원 실패',
  worker_error: '작업 오류',
};

/** Where a provenance-tracked field came from, e.g. the abstract's source API. */
export function provenanceSource(provenance: Record<string, unknown>, field: string): string | null {
  const entry = provenance?.[field];
  if (entry && typeof entry === 'object' && 'source' in entry) return String((entry as { source: unknown }).source);
  return null;
}

export function relevanceLabel(score: number | null): { label: string; tone: 'high' | 'mid' | 'low' | 'none' } {
  if (score === null || score === undefined) return { label: '관련도 —', tone: 'none' };
  if (score >= 0.8) return { label: '높은 관련도', tone: 'high' };
  if (score >= 0.5) return { label: '관련도 보통', tone: 'mid' };
  return { label: '관련도 낮음', tone: 'low' };
}
