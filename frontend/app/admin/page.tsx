"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

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
  const [users, setUsers] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = () =>
    api
      .listUsers()
      .then(setUsers)
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl">Admin</h1>
        <p className="text-slate">Manage users and assign roles across the platform.</p>
      </div>
      {error && <p className="text-clay">{error}</p>}
      {message && <p className="text-pine">{message}</p>}
      <div className="space-y-3">
        {users.map((u) => (
          <div key={u.id} className="card-panel p-4 flex flex-wrap gap-3 items-center justify-between">
            <div>
              <p className="font-semibold">{u.full_name}</p>
              <p className="text-sm text-slate">{u.email}</p>
              <p className="text-xs mt-1">{u.roles?.map((r: any) => r.name).join(", ")}</p>
            </div>
            <div className="flex gap-2 items-center">
              <select id={`role-${u.id}`} className="input w-40" defaultValue="contractor">
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
              <button
                className="btn-primary text-sm"
                onClick={async () => {
                  const sel = document.getElementById(`role-${u.id}`) as HTMLSelectElement;
                  try {
                    await api.assignRole(u.id, sel.value);
                    setMessage(`Assigned ${sel.value} to ${u.email}`);
                    load();
                  } catch (err: any) {
                    setError(err.message);
                  }
                }}
              >
                Assign role
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
