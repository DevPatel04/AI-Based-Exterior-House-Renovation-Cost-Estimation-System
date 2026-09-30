"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { api, setToken } from "@/lib/api";

const ROLES = [
  "homeowner",
  "contractor",
  "architect",
  "builder",
  "consultant",
  "supplier",
  "admin",
];

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    email: "",
    password: "",
    full_name: "",
    phone: "",
    company: "",
    role: "homeowner",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await api.register(form);
      const data = await api.login(form.email, form.password);
      setToken(data.access_token);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-lg mx-auto card-panel p-8">
      <h1 className="font-display text-3xl mb-2">Create account</h1>
      <p className="text-slate mb-6">Choose your role to get the right workspace.</p>
      <form onSubmit={onSubmit} className="space-y-4">
        {(["full_name", "email", "password", "phone", "company"] as const).map((key) => (
          <div key={key}>
            <label className="text-sm font-semibold capitalize">{key.replace("_", " ")}</label>
            <input
              type={key === "password" ? "password" : "text"}
              className="input mt-1"
              required={key === "full_name" || key === "email" || key === "password"}
              value={(form as any)[key]}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
            />
          </div>
        ))}
        <div>
          <label className="text-sm font-semibold">Role</label>
          <select
            className="input mt-1"
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value })}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
        {error && <p className="text-clay text-sm">{error}</p>}
        <button className="btn-primary w-full" disabled={loading}>
          {loading ? "Creating…" : "Create account"}
        </button>
      </form>
      <p className="mt-4 text-sm text-slate">
        Already registered? <Link href="/login" className="text-pine font-semibold">Log in</Link>
      </p>
    </div>
  );
}
