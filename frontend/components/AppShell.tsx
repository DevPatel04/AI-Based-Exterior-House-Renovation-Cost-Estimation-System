"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, clearToken, getToken } from "@/lib/api";
import { Icon, IconName } from "@/components/icons";
import { ToastProvider } from "@/components/Toast";
import { humanize, initials, PageLoader } from "@/components/ui";

const PUBLIC_PATHS = ["/", "/login", "/register"];

type AuthState = {
  user: any;
  roles: string[];
  /** true until the first /me check for the current token finishes */
  loading: boolean;
  refreshUser: () => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthState>({
  user: null,
  roles: [],
  loading: true,
  refreshUser: async () => {},
  logout: () => {},
});

export const useAuth = () => useContext(AuthContext);

type NavItem = { href: string; label: string; icon: IconName; match: (p: string) => boolean; show: boolean };

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);
  const isPublic = PUBLIC_PATHS.includes(pathname);

  const refreshUser = useCallback(async () => {
    const me = await api.me();
    setUser(me);
  }, []);

  useEffect(() => {
    setMobileOpen(false);
    const token = getToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      if (!PUBLIC_PATHS.includes(pathname)) router.push("/login");
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => {
        clearToken();
        setUser(null);
        if (!PUBLIC_PATHS.includes(pathname)) router.push("/login");
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  const roles: string[] = user?.roles?.map((r: any) => r.name) || [];
  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    router.push("/login");
  }, [router]);

  const nav: NavItem[] = [
    {
      href: "/dashboard",
      label: "Projects",
      icon: "folder",
      match: (p) => p === "/dashboard" || p.startsWith("/projects"),
      show: true,
    },
    {
      href: "/catalog",
      label: "Catalog",
      icon: "box",
      match: (p) => p.startsWith("/catalog"),
      show: roles.includes("supplier") || roles.includes("admin"),
    },
    {
      href: "/admin",
      label: "Admin",
      icon: "shield",
      match: (p) => p.startsWith("/admin"),
      show: roles.includes("admin"),
    },
  ];
  const visibleNav = nav.filter((n) => n.show);

  // Protected pages wait for the session check instead of flashing content / errors.
  const gate = !isPublic && !user;

  return (
    <AuthContext.Provider value={{ user, roles, loading, refreshUser, logout }}>
      <ToastProvider>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[70] focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:shadow-pop"
        >
          Skip to content
        </a>
        <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/85 backdrop-blur supports-[backdrop-filter]:bg-white/70">
          <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
            <div className="flex items-center gap-8">
              <Link href={user ? "/dashboard" : "/"} className="flex items-center gap-2" aria-label="FacadePlan home">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white shadow-sm">
                  <Icon name="home" className="h-[18px] w-[18px]" />
                </span>
                <span className="font-display text-xl font-semibold text-slate-900">
                  Facade<span className="text-accent-600">Plan</span>
                </span>
              </Link>
              {user && (
                <nav className="hidden items-center gap-1 md:flex" aria-label="Main">
                  {visibleNav.map((item) => {
                    const active = item.match(pathname);
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        className={clsx(
                          "inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                          active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                        )}
                      >
                        <Icon name={item.icon} />
                        {item.label}
                      </Link>
                    );
                  })}
                </nav>
              )}
            </div>

            <div className="flex items-center gap-2">
              {user ? (
                <>
                  <UserMenu user={user} roles={roles} onLogout={logout} />
                  <button
                    type="button"
                    className="btn-icon md:hidden"
                    aria-label={mobileOpen ? "Close menu" : "Open menu"}
                    aria-expanded={mobileOpen}
                    onClick={() => setMobileOpen((o) => !o)}
                  >
                    <Icon name={mobileOpen ? "x" : "menu"} className="h-5 w-5" />
                  </button>
                </>
              ) : (
                !loading && (
                  <>
                    <Link href="/login" className="btn-ghost">
                      Log in
                    </Link>
                    <Link href="/register" className="btn-primary">
                      Get started
                    </Link>
                  </>
                )
              )}
            </div>
          </div>

          {user && mobileOpen && (
            <nav className="animate-fade-in border-t border-slate-200 bg-white px-4 py-3 md:hidden" aria-label="Mobile">
              <div className="flex flex-col gap-1">
                {[...visibleNav, { href: "/profile", label: "Profile", icon: "user" as IconName, match: (p: string) => p === "/profile", show: true }].map(
                  (item) => {
                    const active = item.match(pathname);
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        className={clsx(
                          "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium",
                          active ? "bg-brand-50 text-brand-700" : "text-slate-700 hover:bg-slate-100"
                        )}
                      >
                        <Icon name={item.icon} />
                        {item.label}
                      </Link>
                    );
                  }
                )}
                <button
                  type="button"
                  onClick={logout}
                  className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm font-medium text-slate-700 hover:bg-slate-100"
                >
                  <Icon name="logout" />
                  Log out
                </button>
              </div>
            </nav>
          )}
        </header>

        <main id="main" className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10">
          {gate ? <PageLoader label="Checking your session…" /> : children}
        </main>
        <footer className="mx-auto max-w-7xl px-4 pb-8 pt-2 text-xs text-slate-400 sm:px-6">
          FacadePlan · Estimates are advisory and not legally binding.
        </footer>
      </ToastProvider>
    </AuthContext.Provider>
  );
}

function UserMenu({ user, roles, onLogout }: { user: any; roles: string[]; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-3 rounded-full py-1 pl-1 pr-1 transition-colors hover:bg-slate-100 sm:pr-3"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-100 text-xs font-bold text-accent-700">
          {initials(user.full_name)}
        </span>
        <span className="hidden text-left leading-tight sm:block">
          <span className="block max-w-[10rem] truncate text-sm font-semibold text-slate-900">{user.full_name}</span>
          <span className="block max-w-[10rem] truncate text-xs text-slate-500">{roles.map(humanize).join(", ")}</span>
        </span>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-2 w-64 animate-fade-in overflow-hidden rounded-xl border border-slate-200 bg-white shadow-pop"
        >
          <div className="border-b border-slate-100 px-4 py-3">
            <p className="truncate text-sm font-semibold text-slate-900">{user.full_name}</p>
            <p className="truncate text-xs text-slate-500">{user.email}</p>
          </div>
          <div className="p-1">
            <Link
              role="menuitem"
              href="/profile"
              className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
            >
              <Icon name="user" /> Profile & branding
            </Link>
            <button
              role="menuitem"
              type="button"
              onClick={onLogout}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-100"
            >
              <Icon name="logout" /> Log out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
