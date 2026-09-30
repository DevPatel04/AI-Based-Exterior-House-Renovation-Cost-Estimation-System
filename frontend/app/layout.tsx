"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { api, clearToken, getToken } from "@/lib/api";
import "./globals.css";

export default function RootLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const publicPaths = ["/", "/login", "/register"];

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setUser(null);
      if (!publicPaths.includes(pathname)) router.push("/login");
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => {
        clearToken();
        setUser(null);
        if (!publicPaths.includes(pathname)) router.push("/login");
      });
  }, [pathname]);

  const roles = user?.roles?.map((r: any) => r.name) || [];
  const logout = () => {
    clearToken();
    setUser(null);
    router.push("/login");
  };

  return (
    <html lang="en">
      <body>
        <header className="border-b border-mist/80 bg-white/70 backdrop-blur sticky top-0 z-40">
          <div className="mx-auto max-w-6xl px-4 py-3 flex items-center justify-between gap-4">
            <Link href={user ? "/dashboard" : "/"} className="font-display text-xl text-ink">
              Facade<span className="text-clay">Plan</span>
            </Link>
            <nav className="flex items-center gap-3 text-sm">
              {user ? (
                <>
                  <Link className="hover:text-pine" href="/dashboard">
                    Projects
                  </Link>
                  <Link className="hover:text-pine" href="/profile">
                    Profile
                  </Link>
                  {(roles.includes("supplier") || roles.includes("admin")) && (
                    <Link className="hover:text-pine" href="/catalog">
                      Catalog
                    </Link>
                  )}
                  {roles.includes("admin") && (
                    <Link className="hover:text-pine" href="/admin">
                      Admin
                    </Link>
                  )}
                  <span className="text-slate hidden sm:inline">
                    {user.full_name} · {roles.join(", ")}
                  </span>
                  <button onClick={logout} className="btn-ghost text-sm py-1.5">
                    Log out
                  </button>
                </>
              ) : (
                <>
                  <Link href="/login" className="hover:text-pine">
                    Log in
                  </Link>
                  <Link href="/register" className="btn-primary text-sm py-1.5">
                    Get started
                  </Link>
                </>
              )}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
