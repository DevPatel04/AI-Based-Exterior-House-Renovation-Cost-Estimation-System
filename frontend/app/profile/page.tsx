"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, API_URL, getToken } from "@/lib/api";
import { useAuth } from "@/components/AppShell";
import { Icon } from "@/components/icons";
import { useToast } from "@/components/Toast";
import { Alert, Badge, Card, Field, FileButton, humanize, initials, PageHeader, PageLoader, Spinner } from "@/components/ui";

export default function ProfilePage() {
  const toast = useToast();
  const { refreshUser } = useAuth();
  const [me, setMe] = useState<any>(null);
  const [form, setForm] = useState({ full_name: "", phone: "", company: "" });
  const [logoUrl, setLogoUrl] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);

  async function load() {
    const me = await api.me();
    setMe(me);
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
    setSaving(true);
    try {
      await api.updateMe(form);
      toast.success("Profile saved.");
      refreshUser().catch(() => {});
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function onLogo(file: File) {
    setUploading(true);
    try {
      await api.uploadLogo(file);
      toast.success("Logo uploaded — it will appear on your PDF reports.");
      await load();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setUploading(false);
    }
  }

  if (!me) {
    return error ? <Alert tone="error" title="Couldn't load your profile">{error}</Alert> : <PageLoader />;
  }

  const roles: string[] = me.roles?.map((r: any) => r.name) || [];

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <PageHeader title="Profile" description="Update your contact details and the logo used to brand your reports." />

      <div className="card-panel flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:p-6">
        <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-accent-100 text-lg font-bold text-accent-700">
          {initials(me.full_name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-lg font-semibold text-slate-900">{me.full_name}</p>
          <p className="truncate text-sm text-slate-500">{me.email}</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {roles.map((r) => (
            <Badge key={r} tone={r === "admin" ? "violet" : "brand"}>
              {humanize(r)}
            </Badge>
          ))}
        </div>
      </div>

      <Card title="Contact details" description="Shown to collaborators and on generated reports.">
        <form onSubmit={onSave} className="space-y-5">
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Full name" required className="sm:col-span-2">
              {(id) => (
                <input
                  id={id}
                  className="input"
                  autoComplete="name"
                  value={form.full_name}
                  onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                  required
                />
              )}
            </Field>
            <Field label="Phone">
              {(id) => (
                <input
                  id={id}
                  type="tel"
                  className="input"
                  autoComplete="tel"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              )}
            </Field>
            <Field label="Company">
              {(id) => (
                <input
                  id={id}
                  className="input"
                  autoComplete="organization"
                  value={form.company}
                  onChange={(e) => setForm({ ...form, company: e.target.value })}
                />
              )}
            </Field>
          </div>
          <div className="flex justify-end border-t border-slate-100 pt-5">
            <button className="btn-primary" disabled={saving}>
              {saving && <Spinner />}
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </form>
      </Card>

      <Card
        title="Report branding"
        description="Consultants and contractors can add a logo that appears on downloaded PDF reports."
      >
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
          <div className="flex h-24 w-40 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-dashed border-slate-300 bg-slate-50">
            {logoUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={logoUrl} alt="Your report logo" className="max-h-full max-w-full object-contain p-2" />
            ) : (
              <span className="flex flex-col items-center gap-1 text-xs text-slate-400">
                <Icon name="image" className="h-6 w-6" />
                No logo yet
              </span>
            )}
          </div>
          <div className="space-y-2">
            <FileButton onFile={onLogo} busy={uploading}>
              {uploading ? "Uploading…" : logoUrl ? "Replace logo" : "Upload logo"}
            </FileButton>
            <p className="text-xs text-slate-500">PNG or JPG with a transparent or white background works best.</p>
          </div>
        </div>
      </Card>
    </div>
  );
}
