"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";

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

export default function CatalogPage() {
  const [materials, setMaterials] = useState<any[]>([]);
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
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = () => api.listMaterials().then(setMaterials).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    try {
      await api.createMaterial(form);
      setMessage("Material submitted (admin approval may be required).");
      setForm({ ...form, name: "" });
      load();
    } catch (err: any) {
      setError(err.message);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl">Material catalog</h1>
        <p className="text-slate">Suppliers and admins manage materials, rates, and suitability notes.</p>
      </div>
      <form onSubmit={onCreate} className="card-panel p-6 grid md:grid-cols-2 gap-3">
        <input
          className="input"
          placeholder="Name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          required
        />
        <select
          className="input"
          value={form.material_type}
          onChange={(e) => setForm({ ...form, material_type: e.target.value })}
        >
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <input
          className="input"
          type="number"
          placeholder="Material rate"
          value={form.material_rate}
          onChange={(e) => setForm({ ...form, material_rate: Number(e.target.value) })}
        />
        <input
          className="input"
          type="number"
          placeholder="Labor rate"
          value={form.labor_rate}
          onChange={(e) => setForm({ ...form, labor_rate: Number(e.target.value) })}
        />
        <input
          className="input md:col-span-2"
          placeholder="Description"
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />
        <button className="btn-primary md:col-span-2">Add material</button>
      </form>
      {message && <p className="text-pine text-sm">{message}</p>}
      {error && <p className="text-clay text-sm">{error}</p>}
      <div className="grid md:grid-cols-2 gap-3">
        {materials.map((m) => (
          <div key={m.id} className="card-panel p-4">
            <div className="flex justify-between gap-2">
              <h2 className="font-semibold">{m.name}</h2>
              <span className="text-xs bg-mist px-2 py-1 rounded">{m.material_type}</span>
            </div>
            <p className="text-sm text-slate mt-1">
              ₹{m.material_rate}/{m.unit} mat · ₹{m.labor_rate} labor · {m.wastage_percent}% wastage
            </p>
            <p className="text-xs mt-2">{m.approved ? "Approved" : "Pending approval"} · {m.is_active ? "Active" : "Inactive"}</p>
            {m.suitable_regions?.length ? (
              <p className="text-xs text-slate mt-1">Suits: {m.suitable_regions.join(", ")}</p>
            ) : null}
            <div className="mt-2">
              <label className="text-xs font-semibold">Upload texture image</label>
              <input
                type="file"
                accept="image/*"
                className="block text-xs mt-1"
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  try {
                    await api.uploadTexture(m.id, f);
                    setMessage(`Texture added to ${m.name}`);
                  } catch (err: any) {
                    setError(err.message);
                  }
                }}
              />
            </div>
            {!m.approved && (
              <button
                className="btn-ghost mt-2 text-sm"
                onClick={async () => {
                  try {
                    await api.updateMaterial(m.id, { approved: true });
                    load();
                  } catch (err: any) {
                    setError(err.message);
                  }
                }}
              >
                Approve (admin)
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
