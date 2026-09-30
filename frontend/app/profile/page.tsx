"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, API_URL, getToken } from "@/lib/api";

export default function ProfilePage() {
  const [form, setForm] = useState({ full_name: "", phone: "", company: "" });
  const [logoUrl, setLogoUrl] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const me = await api.me();
    setForm({
      full_name: me.full_name || "",
      phone: me.phone || "",
      company: me.company || "",
    });
    if (me.logo_path) {
      const token = getToken();
      const res = await fetch(`${API_URL}/api/auth/me/logo`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) setLogoUrl(URL.createObjectURL(await res.blob()));
    }
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.updateMe(form);
      setMessage("Profile saved.");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function onLogo(file: File) {
    setBusy(true);
    setError("");
    try {
      await api.uploadLogo(file);
      setMessage("Logo uploaded — it will appear on PDF reports.");
      await load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-xl space-y-6">
      <div>
        <h1 className="font-display text-4xl">Profile</h1>
        <p className="text-slate">Update contact details and report branding logo.</p>
      </div>
      <form onSubmit={onSave} className="card-panel p-6 space-y-4">
        {(["full_name", "phone", "company"] as const).map((key) => (
          <div key={key}>
            <label className="text-sm font-semibold capitalize">{key.replace("_", " ")}</label>
            <input
              className="input mt-1"
              value={form[key]}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              required={key === "full_name"}
            />
          </div>
        ))}
        <button className="btn-primary" disabled={busy}>
          Save profile
        </button>
      </form>

      <div className="card-panel p-6 space-y-3">
        <h2 className="font-semibold">Report logo (J8)</h2>
        <p className="text-sm text-slate">Consultants and contractors: upload a logo for PDF branding.</p>
        {logoUrl && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={logoUrl} alt="Logo" className="h-16 object-contain bg-white rounded border border-mist p-2" />
        )}
        <input
          type="file"
          accept="image/*"
          onChange={(e) => e.target.files?.[0] && onLogo(e.target.files[0])}
        />
      </div>

      {message && <p className="text-pine text-sm">{message}</p>}
      {error && <p className="text-clay text-sm">{error}</p>}
      {busy && <p className="text-slate text-sm">Working…</p>}
    </div>
  );
}
