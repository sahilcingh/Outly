"use client";

import { useRouter } from "next/navigation";
import { useAuth } from "./auth-context";
import { API_BASE_URL } from "./config";

export default function UserMenu() {
  const { email } = useAuth();
  const router = useRouter();
  if (!email) return null;

  const handleLogout = async () => {
    try {
      await fetch(`${API_BASE_URL}/logout`, { credentials: "include" });
    } catch (err) {
      console.error("Logout failed", err);
    }
    router.push("/login");
    router.refresh();
  };

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-muted">{email}</span>
      <button onClick={handleLogout} className="nav-link" style={{ background: "none", border: "none", cursor: "pointer" }}>
        Logout
      </button>
    </div>
  );
}
