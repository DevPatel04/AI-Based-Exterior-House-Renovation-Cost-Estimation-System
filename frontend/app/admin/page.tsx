"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Icon } from "@/components/icons";
import { useToast } from "@/components/Toast";
import {
  Alert,
  Badge,
  EmptyState,
  formatDate,
  humanize,
  initials,
  PageHeader,
  Spinner,
} from "@/components/ui";

const ROLES = [
  "homeowner",
  "contractor",
  "architect",
  "builder",
  "consultant",
  "supplier",
  "admin",
];

export default function AdminPage() {
  const toast = useToast();
  const [users, setUsers] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<Record<number, string>>({});
  const [savingId, setSavingId] = useState<number | null>(null);

  const load = () =>
    api
      .listUsers()
      .then((u) => {
        setUsers(u);
        setError("");
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  async function assign(u: any) {
    const role = selection[u.id] || "contractor";
    setSavingId(u.id);
    try {
      await api.assignRole(u.id, role);
      toast.success(`Assigned ${humanize(role)} to ${u.email}`);
      await load();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setSavingId(null);
    }
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!users) return [];
    if (!q) return users;
    return users.filter(
      (u) =>
        u.full_name?.toLowerCase().includes(q) ||
        u.email?.toLowerCase().includes(q) ||
        u.roles?.some((r: any) => r.name.includes(q))
    );
  }, [users, query]);

  return (
    <div className="space-y-8">
      <PageHeader
        title="User management"
        description="Review accounts and assign roles across the platform."
        actions={users && <Badge tone="neutral">{users.length} users</Badge>}
      />

      {error && (
        <Alert tone="error" title="Couldn't load users">
          {error}{" "}
          <button className="link" onClick={load}>
            Try again
          </button>
        </Alert>
      )}

      <div className={users === null && error ? "hidden" : "card-panel overflow-hidden"}>
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative w-full sm:max-w-xs">
            <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="search"
              className="input pl-9"
              placeholder="Search by name, email or role"
              aria-label="Search users"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        </div>

        {users === null && error ? null : users === null ? (
          <div className="space-y-3 p-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton h-12" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-4">
            <EmptyState icon="users" title="No users found" description={query ? `Nothing matches “${query}”.` : undefined} />
          </div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {filtered.map((u) => {
              const roles: string[] = u.roles?.map((r: any) => r.name) || [];
              const selectId = `role-${u.id}`;
              return (
                <li key={u.id} className="flex flex-col gap-4 p-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-100 text-sm font-bold text-slate-600">
                      {initials(u.full_name)}
                    </span>
                    <div className="min-w-0">
                      <p className="flex items-center gap-2 truncate font-semibold text-slate-900">
                        {u.full_name}
                        {u.is_active === false && <Badge tone="danger">Inactive</Badge>}
                      </p>
                      <p className="truncate text-sm text-slate-500">
                        {u.email}
                        {u.created_at && <span className="hidden sm:inline"> · Joined {formatDate(u.created_at)}</span>}
                      </p>
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {roles.length ? (
                          roles.map((r) => (
                            <Badge key={r} tone={r === "admin" ? "violet" : "brand"}>
                              {humanize(r)}
                            </Badge>
                          ))
                        ) : (
                          <Badge>No role</Badge>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <label htmlFor={selectId} className="sr-only">
                      Role to assign to {u.full_name}
                    </label>
                    <select
                      id={selectId}
                      className="input w-full sm:w-44"
                      value={selection[u.id] || "contractor"}
                      onChange={(e) => setSelection({ ...selection, [u.id]: e.target.value })}
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {humanize(r)}
                        </option>
                      ))}
                    </select>
                    <button className="btn-primary shrink-0" onClick={() => assign(u)} disabled={savingId === u.id}>
                      {savingId === u.id && <Spinner />}
                      Assign role
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
