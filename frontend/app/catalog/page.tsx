"use client";

import clsx from "clsx";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/AppShell";
import { Icon } from "@/components/icons";
import { useToast } from "@/components/Toast";
import {
  Alert,
  Badge,
  Card,
  EmptyState,
  Field,
  FileButton,
  formatINR,
  humanize,
  PageHeader,
  Spinner,
} from "@/components/ui";

const TYPES = [
  "paint",
  "stone_cladding",
  "tiles",
  "texture_finish",
  "glass_railing",
  "metal_railing",
  "panels",
  "other",
];

// Units understood by the estimation service (liter/bag/piece/panel use coverage per unit).
const UNITS = ["sq_ft", "liter", "bag", "piece", "panel"];

export default function CatalogPage() {
  const toast = useToast();
  const { roles } = useAuth();
  const isAdmin = roles.includes("admin");
  const [materials, setMaterials] = useState<any[] | null>(null);
  const [form, setForm] = useState({
    name: "",
    material_type: "paint",
    unit: "sq_ft",
    coverage_per_unit: 1,
    wastage_percent: 10,
    material_rate: 100,
    labor_rate: 20,
    description: "",
  });
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  const load = () =>
    api
      .listMaterials(true)
      .then((m) => {
        setMaterials(m);
        setError("");
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await api.createMaterial(form);
      toast.success("Material submitted. Admin approval may be required before it appears in designs.");
      setForm({ ...form, name: "" });
      load();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  const num = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: Number(e.target.value) });

  const filtered = useMemo(() => {
    if (!materials) return [];
    const q = query.trim().toLowerCase();
    return materials.filter(
      (m) =>
        (!typeFilter || m.material_type === typeFilter) &&
        (!q || m.name?.toLowerCase().includes(q) || m.description?.toLowerCase().includes(q))
    );
  }, [materials, query, typeFilter]);

  const pendingCount = materials?.filter((m) => !m.approved).length ?? 0;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Material catalog"
        description="Manage materials, rates, and coverage used for redesigns and cost estimates."
        actions={
          materials && (
            <>
              <Badge>{materials.length} materials</Badge>
              {pendingCount > 0 && <Badge tone="warning">{pendingCount} pending approval</Badge>}
            </>
          )
        }
      />

      {error && (
        <Alert tone="error" title="Couldn't load materials">
          {error}{" "}
          <button className="link" onClick={load}>
            Try again
          </button>
        </Alert>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,380px)_1fr]">
        <Card title="Add material" description="New materials may need admin approval." className="lg:sticky lg:top-24">
          <form onSubmit={onCreate} className="space-y-4">
            <Field label="Name" required>
              {(id) => (
                <input
                  id={id}
                  className="input"
                  placeholder="e.g. Weatherproof exterior emulsion"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  required
                />
              )}
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Type">
                {(id) => (
                  <select
                    id={id}
                    className="input"
                    value={form.material_type}
                    onChange={(e) => setForm({ ...form, material_type: e.target.value })}
                  >
                    {TYPES.map((t) => (
                      <option key={t} value={t}>
                        {humanize(t)}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <Field label="Unit">
                {(id) => (
                  <select id={id} className="input" value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })}>
                    {UNITS.map((u) => (
                      <option key={u} value={u}>
                        {u.replace("_", " ")}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <Field label="Material rate (₹)">
                {(id) => (
                  <input id={id} className="input" type="number" min={0} step="any" inputMode="decimal" value={form.material_rate} onChange={num("material_rate")} />
                )}
              </Field>
              <Field label="Labor rate (₹)">
                {(id) => (
                  <input id={id} className="input" type="number" min={0} step="any" inputMode="decimal" value={form.labor_rate} onChange={num("labor_rate")} />
                )}
              </Field>
              <Field label="Coverage / unit" hint="sq ft per unit">
                {(id) => (
                  <input id={id} className="input" type="number" min={0} step="any" inputMode="decimal" value={form.coverage_per_unit} onChange={num("coverage_per_unit")} />
                )}
              </Field>
              <Field label="Wastage (%)">
                {(id) => (
                  <input id={id} className="input" type="number" min={0} max={100} step="any" inputMode="decimal" value={form.wastage_percent} onChange={num("wastage_percent")} />
                )}
              </Field>
            </div>
            <Field label="Description" hint="Optional — finish, durability or suitability notes">
              {(id) => (
                <textarea
                  id={id}
                  rows={2}
                  className="input resize-none"
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                />
              )}
            </Field>
            <button className="btn-primary w-full" disabled={submitting}>
              {submitting ? <Spinner /> : <Icon name="plus" />}
              {submitting ? "Adding…" : "Add material"}
            </button>
          </form>
        </Card>

        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                className="input pl-9"
                placeholder="Search materials"
                aria-label="Search materials"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <select
              className="input sm:w-48"
              aria-label="Filter by type"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
            >
              <option value="">All types</option>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {humanize(t)}
                </option>
              ))}
            </select>
          </div>

          {materials === null && error ? null : materials === null ? (
            <div className="grid gap-4 md:grid-cols-2">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="card-panel space-y-3 p-5">
                  <div className="skeleton h-5 w-1/2" />
                  <div className="skeleton h-4 w-3/4" />
                  <div className="skeleton h-8 w-1/3" />
                </div>
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon="box"
              title={materials.length ? "No matching materials" : "No materials yet"}
              description={materials.length ? "Try a different search or type filter." : "Add your first material using the form."}
            />
          ) : (
            <ul className="grid gap-4 md:grid-cols-2">
              {filtered.map((m) => (
                <li key={m.id} className={clsx("card-panel flex flex-col p-5", !m.approved && "border-amber-200")}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="truncate font-semibold text-slate-900">{m.name}</h2>
                      <p className="mt-0.5 text-xs text-slate-500">{humanize(m.material_type)}</p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      {m.approved ? <Badge tone="success" dot>Approved</Badge> : <Badge tone="warning" dot>Pending</Badge>}
                      {!m.is_active && <Badge tone="neutral">Inactive</Badge>}
                    </div>
                  </div>

                  <dl className="mt-4 grid grid-cols-3 gap-2 rounded-lg bg-slate-50 p-3 text-center">
                    <div>
                      <dt className="text-[11px] uppercase tracking-wide text-slate-500">Material</dt>
                      <dd className="text-sm font-semibold tabular-nums text-slate-900">
                        {formatINR(m.material_rate)}
                        <span className="font-normal text-slate-500">/{m.unit?.replace("_", " ")}</span>
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[11px] uppercase tracking-wide text-slate-500">Labor</dt>
                      <dd className="text-sm font-semibold tabular-nums text-slate-900">{formatINR(m.labor_rate)}</dd>
                    </div>
                    <div>
                      <dt className="text-[11px] uppercase tracking-wide text-slate-500">Wastage</dt>
                      <dd className="text-sm font-semibold tabular-nums text-slate-900">{m.wastage_percent}%</dd>
                    </div>
                  </dl>

                  {m.description && <p className="mt-3 line-clamp-2 text-sm text-slate-600">{m.description}</p>}
                  {m.suitable_regions?.length ? (
                    <div className="mt-3 flex flex-wrap gap-1">
                      {m.suitable_regions.map((r: string) => (
                        <Badge key={r} tone="brand">
                          {humanize(r)}
                        </Badge>
                      ))}
                    </div>
                  ) : null}

                  <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
                    <FileButton
                      className="btn-outline btn-sm"
                      busy={busyId === m.id}
                      onFile={async (f) => {
                        setBusyId(m.id);
                        try {
                          await api.uploadTexture(m.id, f);
                          toast.success(`Texture added to ${m.name}`);
                        } catch (err: any) {
                          toast.error(err.message);
                        } finally {
                          setBusyId(null);
                        }
                      }}
                    >
                      Upload texture
                    </FileButton>
                    {!m.approved && isAdmin && (
                      <button
                        className="btn-primary btn-sm"
                        disabled={busyId === m.id}
                        onClick={async () => {
                          setBusyId(m.id);
                          try {
                            await api.updateMaterial(m.id, { approved: true });
                            toast.success(`${m.name} approved`);
                            await load();
                          } catch (err: any) {
                            toast.error(err.message);
                          } finally {
                            setBusyId(null);
                          }
                        }}
                      >
                        <Icon name="check" /> Approve
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
