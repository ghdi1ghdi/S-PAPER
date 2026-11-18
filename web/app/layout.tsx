// Pretendard is bundled from node_modules so the strict CSP (style/font 'self') stays intact.
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css';
import './globals.css';
import type { Metadata, Viewport } from 'next';

export const metadata: Metadata = {
  title: 'S-PAPER · 연구 논문 수집',
  description: '주제별 논문 자동 수집, 초록 기반 한국어 요약과 CSV 내보내기',
};
export const viewport: Viewport = { width: 'device-width', initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
