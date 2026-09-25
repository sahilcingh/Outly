"use client";

import { Moon, Sun } from "lucide-react";

/**
 * Flips the `dark` class on <html> and remembers the choice.
 *
 * Deliberately holds no React state: which icon shows is decided by CSS from
 * the class already on <html>, so there is nothing to hydrate and no flash of
 * the wrong icon. The initial class is set by THEME_SCRIPT in layout.tsx.
 */
export default function ThemeToggle({ className = "" }: { className?: string }) {
  const toggle = () => {
    const root = document.documentElement;
    const next = root.classList.toggle("dark") ? "dark" : "light";
    root.style.colorScheme = next;
    try {
      localStorage.setItem("outly-theme", next);
    } catch {
      // Private mode or blocked storage: the toggle still works for this page.
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      className={`theme-toggle ${className}`}
      aria-label="Toggle dark mode"
      title="Toggle dark mode"
    >
      <Sun className="icon-sun" size={16} strokeWidth={2} />
      <Moon className="icon-moon" size={16} strokeWidth={2} />
    </button>
  );
}
