'use client';
import { ReactNode, useEffect, useRef } from 'react';
import { statusName } from '../lib';

const paths: Record<string, ReactNode> = {
  home: <path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />,
  radar: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <path d="M12 12 18 6" />
    </>
  ),
  library: (
    <>
      <path d="M4 4h4v16H4zM10 4h4v16h-4z" />
      <path d="m16 5 3.8-1 2.2 15.5-3.8 1z" />
    </>
  ),
  history: (
    <>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5M12 7v5l3 2" />
    </>
  ),
  shield: <path d="M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6z" />,
  plus: <path d="M12 5v14M5 12h14" />,
  download: <path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14" />,
  external: <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  sparkle: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z" />,
  play: <path d="M7 4v16l13-8z" />,
  logout: <path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 17l5-5-5-5M15 12H3" />,
};

export function Icon({ name, size = 18 }: { name: keyof typeof paths | string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="icon"
    >
      {paths[name]}
    </svg>
  );
}

export function Badge({ value }: { value: string }) {
  return <span className={'badge status ' + value}>{statusName[value] || value}</span>;
}

export function Modal({ title, children, close }: { title: string; children: ReactNode; close: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement;
    ref.current?.focus();
    const listener = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
      if (e.key === 'Tab') {
        const els = ref.current?.querySelectorAll<HTMLElement>('button,a,input,select,textarea,[tabindex="0"]');
        if (els?.length) {
          const first = els[0],
            last = els[els.length - 1];
          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };
    document.addEventListener('keydown', listener);
    const old = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', listener);
      document.body.style.overflow = old;
      prev?.focus();
    };
  }, [close]);
  return (
    <div
      className="drawer-bg"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="drawer" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <div className="drawer-header">
          <span className="drawer-title">{title}</span>
          <button className="icon-button" onClick={close} aria-label="닫기">
            <Icon name="close" />
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </div>
    </div>
  );
}

export function RelevanceMeter({ score }: { score: number | null }) {
  if (score === null || score === undefined) return null;
  const pct = Math.round(score * 100);
  const tone = score >= 0.8 ? 'high' : score >= 0.5 ? 'mid' : 'low';
  return (
    <span className={'meter ' + tone} title={`주제 관련도 ${pct}%`} aria-label={`주제 관련도 ${pct}%`}>
      <span className="meter-track">
        <span className="meter-fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="meter-value">{pct}</span>
    </span>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}
