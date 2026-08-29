"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { API_BASE_URL } from "../config";

export default function LoginPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [next, setNext] = useState("/");
  const router = useRouter();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setNext(params.get("next") || "/");
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      const body = new URLSearchParams({ email, password });
      if (mode === "register") body.append("confirm_password", confirmPassword);

      const res = await fetch(`${API_BASE_URL}/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
        credentials: "include",
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        throw new Error(data.error || "Something went wrong.");
      }

      router.push(next);
    } catch (err: any) {
      setError(err.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex justify-center" style={{ marginTop: "4rem" }}>
      <div className="card-light flex flex-col gap-4" style={{ maxWidth: "400px", width: "100%", padding: "2rem" }}>
        <h1 className="text-hero" style={{ fontSize: "1.75rem", marginBottom: "0.25rem" }}>
          {mode === "login" ? "Sign in" : "Create account"}
        </h1>
        <p className="text-subhero" style={{ margin: 0 }}>Access your Outly workspace.</p>

        <form className="flex flex-col gap-4 mt-4" onSubmit={handleSubmit}>
          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium">Email</label>
            <input
              type="email"
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={loading}
              required
            />
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium">Password</label>
            <input
              type="password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
              minLength={8}
              required
            />
          </div>

          {mode === "register" && (
            <div className="flex flex-col gap-2">
              <label className="text-sm font-medium">Confirm Password</label>
              <input
                type="password"
                className="input"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                disabled={loading}
                minLength={8}
                required
              />
            </div>
          )}

          <button type="submit" className={`btn btn-primary mt-2 ${loading ? "pulse" : ""}`} disabled={loading}>
            {loading ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}
          </button>

          {error && (
            <div
              className="p-3 rounded-md text-sm"
              style={{ backgroundColor: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", color: "var(--error)" }}
            >
              {error}
            </div>
          )}
        </form>

        <button
          type="button"
          className="btn btn-secondary mt-2"
          disabled={loading}
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError("");
          }}
        >
          {mode === "login" ? "Need an account? Register" : "Already have an account? Sign in"}
        </button>
      </div>
    </div>
  );
}
