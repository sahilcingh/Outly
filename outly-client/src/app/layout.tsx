import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "./auth-context";
import AppShell from "./AppShell";
import { cn } from "@/lib/utils";
import { TooltipProvider } from "@/components/ui/skiper-ui/skiper101";

const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "Outly / Intelligence",
  description: "Automated B2B research agent",
};

// Runs before first paint so the page never flashes light before going dark.
// Falls back to the OS preference until the user picks a side.
const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem('outly-theme');
if(t!=='light'&&t!=='dark'){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}
if(t==='dark'){document.documentElement.classList.add('dark')}
document.documentElement.style.colorScheme=t}catch(e){}})()`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={cn("font-sans", inter.variable)} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <TooltipProvider>
          <AuthProvider>
            <AppShell>{children}</AppShell>
          </AuthProvider>
        </TooltipProvider>
      </body>
    </html>
  );
}
