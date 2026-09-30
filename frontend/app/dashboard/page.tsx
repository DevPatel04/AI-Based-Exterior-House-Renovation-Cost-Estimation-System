"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/AppShell";
import { Icon } from "@/components/icons";
import {
  Alert,
  EmptyState,
  Field,
  formatDate,
  Modal,
  PageHeader,
  Spinner,
  StatusBadge,
} from "@/components/ui";

const CREATE_ROLES = ["homeowner", "contractor", "architect", "consultant", "admin"];

export default function DashboardPage() {
  const router = useRouter();
  const { user, roles } = useAuth();
  const [projects, setProjects] = useState<any[] | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [query, setQuery] = useState("");

  const load = async () => {
    setError("");
    try {
      setProjects(await api.listProjects());
    } catch (err: any) {
      setError(err.message);
      setProjects([]);
    }
  };

  useEffect(() => {
    load();
  }, []);

  async function createProject(e: FormEvent) {
    e.preventDefault();
    setCreateError("");
    setCreating(true);
    try {
      const p = await api.createProject({ title, description });
      setTitle("");
      setDescription("");
      router.push(`/projects/${p.id}`);
    } catch (err: any) {
      setCreateError(err.message);
      setCreating(false);
    }
  }

  const canCreate = CREATE_ROLES.some((r) => roles.includes(r));

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!projects) return [];
    if (!q) return projects;
    return projects.filter(
      (p) => p.title?.toLowerCase().includes(q) || p.description?.toLowerCase().includes(q)
    );
  }, [projects, query]);

  const firstName = user?.full_name?.split(" ")[0];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Your projects"
        description={
          firstName
            ? `Welcome back, ${firstName}. Create, reopen, and collaborate on exterior renovation plans.`
            : "Create, reopen, and collaborate on exterior renovation plans."
        }
        actions={
          canCreate && (
            <button className="btn-primary" onClick={() => setShowCreate(true)}>
              <Icon name="plus" /> New project
            </button>
          )
        }
      />

      {error && (
        <Alert tone="error" title="Couldn't load projects">
          {error}{" "}
          <button className="link" onClick={load}>
            Try again
          </button>
        </Alert>
      )}

      {projects && projects.length > 0 && (
        <div className="relative max-w-sm">
          <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="search"
            className="input pl-9"
            placeholder="Search projects"
            aria-label="Search projects"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      )}

      {projects === null ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card-panel space-y-3 p-5">
              <div className="skeleton h-5 w-2/3" />
              <div className="skeleton h-4 w-full" />
              <div className="skeleton h-4 w-1/2" />
            </div>
          ))}
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          icon="home"
          title="No projects yet"
          description={
            canCreate
              ? "Create your first project, then upload a photo of your house to get started."
              : "Projects shared with you will appear here."
          }
          action={
            canCreate && (
              <button className="btn-primary" onClick={() => setShowCreate(true)}>
                <Icon name="plus" /> Create your first project
              </button>
            )
          }
        />
      ) : filtered.length === 0 ? (
        <EmptyState icon="search" title="No matching projects" description={`Nothing matches “${query}”.`} />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((p) => (
            <li key={p.id}>
              <Link
                href={`/projects/${p.id}`}
                className="group card-panel flex h-full flex-col p-5 transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-pop"
              >
                <div className="flex items-start justify-between gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
                    <Icon name="home" className="h-5 w-5" />
                  </span>
                  <StatusBadge status={p.status} />
                </div>
                <h2 className="mt-4 line-clamp-1 text-lg font-semibold text-slate-900 group-hover:text-brand-700">
                  {p.title}
                </h2>
                <p className="mt-1 line-clamp-2 flex-1 text-sm text-slate-500">
                  {p.description || <span className="italic text-slate-400">No description</span>}
                </p>
                <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500">
                  <span>Updated {formatDate(p.updated_at || p.created_at)}</span>
                  <span className="inline-flex items-center gap-1 font-semibold text-brand-700 opacity-0 transition group-hover:opacity-100">
                    Open <Icon name="arrowRight" className="h-3.5 w-3.5" />
                  </span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <Modal
        open={showCreate}
        onClose={() => !creating && setShowCreate(false)}
        title="New project"
        description="Give your project a name. You'll upload a house photo next."
        footer={
          <>
            <button type="button" className="btn-outline" onClick={() => setShowCreate(false)} disabled={creating}>
              Cancel
            </button>
            <button type="submit" form="create-project" className="btn-primary" disabled={creating || !title.trim()}>
              {creating && <Spinner />}
              {creating ? "Creating…" : "Create project"}
            </button>
          </>
        }
      >
        <form id="create-project" onSubmit={createProject} className="space-y-4">
          {createError && <Alert tone="error">{createError}</Alert>}
          <Field label="Project title" required>
            {(id) => (
              <input
                id={id}
                className="input"
                placeholder="e.g. Sharma residence front facade"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            )}
          </Field>
          <Field label="Short description" hint="Optional">
            {(id) => (
              <textarea
                id={id}
                rows={3}
                className="input resize-none"
                placeholder="What are you hoping to change?"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            )}
          </Field>
        </form>
      </Modal>
    </div>
  );
}
