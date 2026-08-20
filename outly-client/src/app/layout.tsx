import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";
import LiveTime from "./LiveTime";

export const metadata: Metadata = {
  title: "Outly / Intelligence",
  description: "Automated B2B research agent",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <div className="app-container">
          <header className="top-nav">
            <div className="flex items-center gap-6">
              <Link href="/" style={{ textDecoration: 'none', color: 'inherit' }}>
                <div className="nav-brand">
                  <div className="brand-icon">O</div>
                  <div>OUTLY / INTELLIGENCE</div>
                </div>
              </Link>
              
              <div className="nav-links ml-8" style={{ marginLeft: '2rem', display: 'flex', gap: '1.5rem' }}>
                <Link href="/" className="nav-link">Prospecting</Link>
                <Link href="/drafts" className="nav-link">Drafts</Link>
                <Link href="/jobs" className="nav-link">Jobs</Link>
              </div>
            </div>
            
            <div className="nav-status">
              <div className="status-dot"></div>
              LIVE INVESTIGATION <LiveTime />
            </div>
          </header>
          
          <main className="main-content">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
