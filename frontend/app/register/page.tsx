"use client";

import clsx from "clsx";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { api, setToken } from "@/lib/api";
import AuthCard from "@/components/AuthCard";
import { Alert, Field, Spinner } from "@/components/ui";

const ROLES: { value: string; label: string; description: string }[] = [
  { value: "homeowner", label: "Homeowner", description: "Plan and visualize your own renovation" },
  { value: "contractor", label: "Contractor", description: "Adjust quantities, rates and quote" },
  { value: "architect", label: "Architect", description: "Refine regions and design options" },
  { value: "builder", label: "Builder", description: "Review quantities and execution costs" },
  { value: "consultant", label: "Consultant", description: "Advise clients with branded reports" },
  { value: "supplier", label: "Material supplier", description: "List materials, rates and textures" },
  { value: "admin", label: "Admin", description: "Manage users, roles and approvals" },
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

  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: e.target.value });

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
    <AuthCard
      wide
      title="Create your account"
      subtitle="Choose your role to get the right workspace."
      footer={
        <>
          Already registered?{" "}
          <Link href="/login" className="link">
            Log in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-6">
        {error && <Alert tone="error">{error}</Alert>}

        <fieldset>
          <legend className="label mb-2">I am a…</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {ROLES.map((r) => {
              const checked = form.role === r.value;
              return (
                <label
                  key={r.value}
                  className={clsx(
                    "flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors",
                    checked ? "border-brand-500 bg-brand-50 ring-1 ring-brand-500" : "border-slate-200 hover:border-slate-300 hover:bg-slate-50"
                  )}
                >
                  <input
                    type="radio"
                    name="role"
                    value={r.value}
                    checked={checked}
                    onChange={set("role")}
                    className="mt-0.5 h-4 w-4 accent-brand-600"
                  />
                  <span>
                    <span className="block text-sm font-semibold text-slate-900">{r.label}</span>
                    <span className="block text-xs text-slate-500">{r.description}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>

        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Full name" required className="sm:col-span-2">
            {(id) => (
              <input id={id} className="input" autoComplete="name" value={form.full_name} onChange={set("full_name")} required />
            )}
          </Field>
          <Field label="Email address" required>
            {(id) => (
              <input
                id={id}
                type="email"
                className="input"
                autoComplete="email"
                placeholder="you@example.com"
                value={form.email}
                onChange={set("email")}
                required
              />
            )}
          </Field>
          <Field label="Password" required hint="At least 6 characters.">
            {(id) => (
              <input
                id={id}
                type="password"
                className="input"
                autoComplete="new-password"
                minLength={6}
                value={form.password}
                onChange={set("password")}
                required
              />
            )}
          </Field>
          <Field label="Phone" hint="Optional">
            {(id) => <input id={id} type="tel" className="input" autoComplete="tel" value={form.phone} onChange={set("phone")} />}
          </Field>
          <Field label="Company" hint="Optional — shown on your reports">
            {(id) => (
              <input id={id} className="input" autoComplete="organization" value={form.company} onChange={set("company")} />
            )}
          </Field>
        </div>

        <button className="btn-primary w-full" disabled={loading}>
          {loading && <Spinner />}
          {loading ? "Creating account…" : "Create account"}
        </button>
      </form>
    </AuthCard>
  );
}
