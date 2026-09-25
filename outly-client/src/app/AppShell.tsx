"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import LiveTime from "./LiveTime";
import UserMenu from "./UserMenu";
import ThemeToggle from "./ThemeToggle";
import { useAuth } from "./auth-context";
import { PageTransition } from "./motion-primitives";
import { OutlyMark } from "@/components/outly-mark";

/** The marketing landing page brings its own header and full-bleed layout. */
export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { email } = useAuth();

  if (pathname === "/") return <>{children}</>;

  // AuthProvider withholds protected routes entirely until it has a session, so
  // the only signed-out page that reaches this header is /login. Show it just
  // the brand and the theme toggle: the workspace links would all bounce back.
  const signedIn = Boolean(email);

  return (
    <div className="app-container">
      <header className="top-nav">
        <div className="flex items-center gap-6">
          <Link href={signedIn ? "/prospecting" : "/"} style={{ textDecoration: "none", color: "inherit" }}>
            <div className="nav-brand">
              <OutlyMark size={24} />
              <div>OUTLY / INTELLIGENCE</div>
            </div>
          </Link>

          {signedIn && (
            <div
              className="nav-links ml-8"
              style={{ marginLeft: "2rem", display: "flex", gap: "1.5rem", flexWrap: "wrap" }}
            >
              <Link href="/prospecting" className="nav-link">Prospecting</Link>
              <Link href="/resume" className="nav-link">Resume</Link>
              <Link href="/batch" className="nav-link">Batch</Link>
              <Link href="/drafts" className="nav-link">Drafts</Link>
              <Link href="/jobs" className="nav-link">Jobs</Link>
              <Link href="/settings/api-keys" className="nav-link">API Keys</Link>
            </div>
          )}
        </div>

        <div className="flex items-center gap-6">
          {signedIn && (
            <div className="nav-status">
              <div className="status-dot"></div>
              LIVE INVESTIGATION <LiveTime />
            </div>
          )}
          <UserMenu />
          <ThemeToggle />
        </div>
      </header>

      <main className="main-content">
        <PageTransition>{children}</PageTransition>
      </main>
    </div>
  );
}
