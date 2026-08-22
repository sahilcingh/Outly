"use client";

import { useAuth } from "./auth-context";

export default function UserMenu() {
  const { email } = useAuth();
  if (!email) return null;

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-muted">{email}</span>
      <a href="/backend/logout" className="nav-link">Logout</a>
    </div>
  );
}
