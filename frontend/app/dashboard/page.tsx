"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function DashboardPage() {
  const [projects, setProjects] = useState<any[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [user, setUser] = useState<any>(null);

  const load = async () => {
    try {
      const [me, list] = await Promise.all([api.me(), api.listProjects()]);
      setUser(me);
      setProjects(list);
    } catch (err: any) {
      setError(err.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  async function createProject(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const p = await api.createProject({ title, description });
      setTitle("");
      setDescription("");
      window.location.href = `/projects/${p.id}`;
    } catch (err: any) {
      setError(err.message);
    }
  }

  const roles = user?.roles?.map((r: any) => r.name) || [];
  const canCreate = ["homeowner", "contractor", "architect", "consultant", "admin"].some((r) =>
    roles.includes(r)
  );

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-4xl">Your projects</h1>
        <p className="text-slate mt-1">Create, reopen, and collaborate on exterior renovation plans.</p>
      </div>

      {canCreate && (
        <form onSubmit={createProject} className="card-panel p-6 grid md:grid-cols-[1fr_1fr_auto] gap-3">
          <input
            className="input"
            placeholder="Project title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
          <input
            className="input"
            placeholder="Short description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <button className="btn-primary">New project</button>
        </form>
      )}

      {error && <p className="text-clay">{error}</p>}

      <div className="grid md:grid-cols-2 gap-4">
        {projects.map((p) => (
          <Link key={p.id} href={`/projects/${p.id}`} className="card-panel p-5 hover:shadow-md transition">
            <div className="flex justify-between items-start gap-3">
              <h2 className="font-display text-2xl">{p.title}</h2>
              <span className="text-xs uppercase tracking-wide bg-mist px-2 py-1 rounded-lg">{p.status}</span>
            </div>
            <p className="text-slate mt-2 line-clamp-2">{p.description || "No description"}</p>
          </Link>
        ))}
        {projects.length === 0 && (
          <p className="text-slate">No projects yet. Create one to upload your house photo.</p>
        )}
      </div>
    </div>
  );
}
