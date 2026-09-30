import Link from "next/link";
import { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "FacadePlan",
  description: "AI-based exterior house renovation & cost estimation",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-mist/80 bg-white/70 backdrop-blur sticky top-0 z-40">
          <div className="mx-auto max-w-6xl px-4 py-3 flex items-center justify-between gap-4">
            <Link href="/" className="font-display text-xl text-ink">
              Facade<span className="text-clay">Plan</span>
            </Link>
            <nav className="flex items-center gap-3 text-sm text-slate">
              <span>Phase 00 scaffold</span>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
