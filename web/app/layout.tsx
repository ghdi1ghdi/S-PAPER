import './globals.css';
import type { Metadata } from 'next';
export const metadata: Metadata = {title:'S-PAPER · 연구 논문 수집', description:'주제별 논문 자동 수집, 초록 기반 한국어 요약과 CSV 내보내기'};
export default function RootLayout({children}:{children:React.ReactNode}) { return <html lang="ko"><body>{children}</body></html>; }
