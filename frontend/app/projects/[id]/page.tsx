"use client";

import dynamic from "next/dynamic";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { api, getToken } from "@/lib/api";

const RegionCanvas = dynamic(() => import("@/components/RegionCanvas"), { ssr: false });

const STEPS = ["Upload", "Regions", "Materials", "Visualize", "Estimate", "Report"] as const;

export default function ProjectWorkspacePage() {
  const params = useParams();
  const projectId = Number(params.id);
  const [step, setStep] = useState(0);
  const [project, setProject] = useState<any>(null);
  const [images, setImages] = useState<any[]>([]);
  const [regions, setRegions] = useState<any[]>([]);
  const [materials, setMaterials] = useState<any[]>([]);
  const [designs, setDesigns] = useState<any[]>([]);
  const [activeDesignId, setActiveDesignId] = useState<number | null>(null);
  const [assignments, setAssignments] = useState<Record<number, number>>({});
  const [areas, setAreas] = useState<any[]>([]);
  const [quantities, setQuantities] = useState<any[]>([]);
  const [costs, setCosts] = useState<any>(null);
  const [reports, setReports] = useState<any[]>([]);
  const [shareEmail, setShareEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [facadeWidth, setFacadeWidth] = useState("30");
  const [facadeHeight, setFacadeHeight] = useState("22");
  const [user, setUser] = useState<any>(null);

  const primary = images.find((i) => i.is_primary) || images[0];
  const activeDesign = designs.find((d) => d.id === activeDesignId) || designs.find((d) => d.is_active);

  const roles = useMemo(() => user?.roles?.map((r: any) => r.name) || [], [user]);

  async function refresh() {
    const [p, imgs, regs, mats, des, me] = await Promise.all([
      api.getProject(projectId),
      api.listImages(projectId),
      api.listRegions(projectId),
      api.listMaterials(),
      api.listDesigns(projectId),
      api.me(),
    ]);
    setProject(p);
    setImages(imgs);
    setRegions(regs);
    setMaterials(mats);
    setDesigns(des);
    setUser(me);
    const active = des.find((d: any) => d.is_active) || des[0];
    if (active) {
      setActiveDesignId(active.id);
      const map = await api.getDesignMaterials(projectId, active.id);
      const obj: Record<number, number> = {};
      map.forEach((m: any) => {
        obj[m.region_id] = m.material_id;
      });
      setAssignments(obj);
    }
    try {
      setAreas(await api.listAreas(projectId));
      setQuantities(await api.listQuantities(projectId));
      setCosts(await api.getCosts(projectId));
      setReports(await api.listReports(projectId));
    } catch {
      /* optional until estimated */
    }
  }

  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, [projectId]);

  async function onUpload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const input = e.currentTarget.elements.namedItem("file") as HTMLInputElement;
    if (!input.files?.[0]) return;
    setBusy(true);
    setError("");
    try {
      const img = await api.uploadImage(projectId, input.files[0]);
      setMessage(img.quality_message || "Uploaded");
      await refresh();
      if (img.quality_ok) setStep(1);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function detect() {
    setBusy(true);
    setError("");
    try {
      const regs = await api.detectRegions(projectId);
      setRegions(regs);
      setMessage(`Detected ${regs.length} regions. Adjust if needed.`);
      setStep(1);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function ensureDesign() {
    if (activeDesignId) return activeDesignId;
    const d = await api.createDesign(projectId, "Design A");
    setDesigns((prev) => [d, ...prev]);
    setActiveDesignId(d.id);
    return d.id as number;
  }

  async function saveAssignments() {
    setBusy(true);
    setError("");
    try {
      const designId = await ensureDesign();
      const items = Object.entries(assignments).map(([region_id, material_id]) => ({
        region_id: Number(region_id),
        material_id: Number(material_id),
      }));
      await api.assignMaterials(projectId, designId, items);
      await api.activateDesign(projectId, designId);
      setMessage("Materials saved on design.");
      await refresh();
      setStep(3);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function runVisualize(hq = false) {
    setBusy(true);
    setError("");
    try {
      const designId = await ensureDesign();
      await api.visualize(projectId, designId, hq);
      setMessage(hq ? "HQ redesign generated." : "Redesign generated.");
      await refresh();
      setStep(3);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function runEstimate() {
    setBusy(true);
    setError("");
    try {
      const a = await api.estimateAreas(projectId, {
        known_width_ft: Number(facadeWidth) || 30,
        known_height_ft: Number(facadeHeight) || 22,
      });
      setAreas(a);
      const c = await api.calculate(projectId);
      setCosts(c);
      setQuantities(await api.listQuantities(projectId));
      setMessage("Areas, quantities, and costs calculated.");
      await refresh();
      setStep(4);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function makeReport() {
    setBusy(true);
    setError("");
    try {
      const designId = activeDesign?.id;
      const r = await api.createReport(projectId, designId);
      setReports(await api.listReports(projectId));
      setMessage("Report ready to download.");
      window.open(`${api.reportDownloadUrl(projectId, r.id)}?access=token`, "_blank");
      // download with auth header via fetch blob
      const token = getToken();
      const res = await fetch(api.reportDownloadUrl(projectId, r.id), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `renovation-report-${projectId}.pdf`;
      a.click();
      setStep(5);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function share(e: FormEvent) {
    e.preventDefault();
    try {
      await api.shareProject(projectId, { user_email: shareEmail, member_role: "editor" });
      setMessage(`Shared with ${shareEmail}`);
      setShareEmail("");
    } catch (err: any) {
      setError(err.message);
    }
  }

  if (!project) {
    return <p className="text-slate">{error || "Loading project…"}</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl">{project.title}</h1>
          <p className="text-slate">{project.description}</p>
          <p className="text-xs uppercase tracking-wide mt-2 text-pine">Status: {project.status}</p>
        </div>
        <form onSubmit={share} className="flex gap-2">
          <input
            className="input"
            placeholder="Share by email"
            value={shareEmail}
            onChange={(e) => setShareEmail(e.target.value)}
          />
          <button className="btn-ghost">Share</button>
        </form>
      </div>

      <div className="flex flex-wrap gap-2">
        {STEPS.map((label, idx) => (
          <button
            key={label}
            onClick={() => setStep(idx)}
            className={`px-3 py-1.5 rounded-full text-sm font-semibold ${
              step === idx ? "bg-pine text-white" : "bg-mist text-ink"
            }`}
          >
            {idx + 1}. {label}
          </button>
        ))}
      </div>

      {message && <p className="text-pine text-sm">{message}</p>}
      {error && <p className="text-clay text-sm">{error}</p>}
      {busy && <p className="text-slate text-sm">Working…</p>}

      {step === 0 && (
        <section className="card-panel p-6 space-y-4">
          <h2 className="font-display text-2xl">Upload exterior photo</h2>
          <p className="text-slate text-sm">
            Use a clear daytime photo of the facade. Low quality images will be rejected with guidance.
          </p>
          <form onSubmit={onUpload} className="flex flex-wrap gap-3 items-center">
            <input name="file" type="file" accept="image/*" className="input" required />
            <button className="btn-primary" disabled={busy}>
              Upload & check quality
            </button>
          </form>
          {primary && (
            <div>
              <AuthImage projectId={projectId} imageId={primary.id} />
              <p className="text-sm mt-2">{primary.quality_ok ? "Quality OK" : "Needs better photo"} — {primary.quality_message}</p>
            </div>
          )}
        </section>
      )}

      {step === 1 && (
        <section className="card-panel p-6 space-y-4">
          <div className="flex flex-wrap gap-3 items-center justify-between">
            <h2 className="font-display text-2xl">Structure regions</h2>
            <button className="btn-primary" onClick={detect} disabled={busy || !primary}>
              Detect with AI
            </button>
          </div>
          {primary ? (
            <RegionCanvas
              projectId={projectId}
              imageId={primary.id}
              regions={regions}
              onChange={setRegions}
            />
          ) : (
            <p className="text-slate">Upload an image first.</p>
          )}
          <button className="btn-secondary" onClick={() => setStep(2)}>
            Continue to materials
          </button>
        </section>
      )}

      {step === 2 && (
        <section className="card-panel p-6 space-y-4">
          <h2 className="font-display text-2xl">Apply materials</h2>
          <div className="space-y-3">
            {regions.map((r) => (
              <div key={r.id} className="grid md:grid-cols-[1fr_2fr] gap-3 items-center">
                <div>
                  <p className="font-semibold">{r.label || r.region_type}</p>
                  <p className="text-xs text-slate">{r.region_type}</p>
                </div>
                <select
                  className="input"
                  value={assignments[r.id] || ""}
                  onChange={(e) =>
                    setAssignments({ ...assignments, [r.id]: Number(e.target.value) })
                  }
                >
                  <option value="">Select material</option>
                  {materials.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name} ({m.material_type}) — ₹{m.material_rate}/{m.unit}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          <button className="btn-primary" onClick={saveAssignments} disabled={busy}>
            Save design & continue
          </button>
        </section>
      )}

      {step === 3 && (
        <section className="card-panel p-6 space-y-4">
          <h2 className="font-display text-2xl">Renovation visualization</h2>
          <div className="flex flex-wrap gap-3">
            <button className="btn-primary" onClick={() => runVisualize(false)} disabled={busy}>
              Generate redesign (Cloudflare / local)
            </button>
            <button className="btn-ghost" onClick={() => runVisualize(true)} disabled={busy}>
              Optional HQ (Gemini)
            </button>
            <button className="btn-secondary" onClick={() => setStep(4)}>
              Continue to estimate
            </button>
          </div>
          <div className="grid md:grid-cols-2 gap-4">
            {primary && (
              <div>
                <p className="text-sm font-semibold mb-2">Original</p>
                <AuthImage projectId={projectId} imageId={primary.id} />
              </div>
            )}
            {activeDesign?.redesign_path && (
              <div>
                <p className="text-sm font-semibold mb-2">Redesigned ({activeDesign.name})</p>
                <AuthImage
                  projectId={projectId}
                  designId={activeDesign.id}
                  kind="redesign"
                />
              </div>
            )}
          </div>
        </section>
      )}

      {step === 4 && (
        <section className="card-panel p-6 space-y-4">
          <h2 className="font-display text-2xl">Area, quantity & cost</h2>
          <div className="grid md:grid-cols-3 gap-3">
            <input
              className="input"
              value={facadeWidth}
              onChange={(e) => setFacadeWidth(e.target.value)}
              placeholder="Facade width ft"
            />
            <input
              className="input"
              value={facadeHeight}
              onChange={(e) => setFacadeHeight(e.target.value)}
              placeholder="Facade height ft"
            />
            <button className="btn-primary" onClick={runEstimate} disabled={busy}>
              Calculate
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left border-b border-mist">
                  <th className="py-2">Region</th>
                  <th>Area sq ft</th>
                  <th>Length ft</th>
                </tr>
              </thead>
              <tbody>
                {areas.map((a) => (
                  <tr key={a.id} className="border-b border-mist/60">
                    <td className="py-2">{a.region_type}</td>
                    <td>{a.area_sq_ft}</td>
                    <td>{a.length_ft ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left border-b border-mist">
                  <th className="py-2">Qty category</th>
                  <th>Final qty</th>
                  <th>Unit</th>
                  <th>Override</th>
                </tr>
              </thead>
              <tbody>
                {quantities.map((q) => (
                  <tr key={q.id} className="border-b border-mist/60">
                    <td className="py-2">{q.category}</td>
                    <td>{q.final_quantity}</td>
                    <td>{q.unit}</td>
                    <td>
                      {(roles.includes("contractor") ||
                        roles.includes("builder") ||
                        roles.includes("admin")) && (
                        <button
                          className="text-pine underline"
                          onClick={async () => {
                            const val = prompt("New final quantity", String(q.final_quantity));
                            if (!val) return;
                            await api.overrideQuantity(projectId, {
                              quantity_line_id: q.id,
                              final_quantity: Number(val),
                            });
                            setQuantities(await api.listQuantities(projectId));
                            setCosts(await api.getCosts(projectId));
                          }}
                        >
                          Edit
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {costs && (
            <div className="bg-mist/50 rounded-xl p-4">
              <p>Material total: <b>₹{costs.material_total}</b></p>
              <p>Labor total: <b>₹{costs.labor_total}</b></p>
              <p className="text-lg">Grand total: <b>₹{costs.grand_total}</b></p>
              <p className="text-xs text-slate mt-2">{costs.disclaimer}</p>
              <div className="mt-3 space-y-2">
                {(costs.lines || []).map((line: any) => (
                  <div key={line.id} className="flex flex-wrap gap-2 items-center text-sm">
                    <span className="min-w-[140px]">{line.category}</span>
                    <input
                      className="input w-28"
                      defaultValue={line.material_rate}
                      onBlur={async (e) => {
                        if (!line.material_id) return;
                        await api.setRates(projectId, {
                          material_id: line.material_id,
                          material_rate: Number(e.target.value),
                        });
                        setCosts(await api.getCosts(projectId));
                      }}
                    />
                    <span>mat rate</span>
                    <input
                      className="input w-28"
                      defaultValue={line.labor_rate}
                      onBlur={async (e) => {
                        if (!line.material_id) return;
                        await api.setRates(projectId, {
                          material_id: line.material_id,
                          labor_rate: Number(e.target.value),
                        });
                        setCosts(await api.getCosts(projectId));
                      }}
                    />
                    <span>labor → ₹{line.total_cost}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <button className="btn-secondary" onClick={() => setStep(5)}>
            Continue to report
          </button>
        </section>
      )}

      {step === 5 && (
        <section className="card-panel p-6 space-y-4">
          <h2 className="font-display text-2xl">Downloadable report</h2>
          <p className="text-slate text-sm">
            Includes original image, redesign, materials, quantities, and cost breakdown for contractor discussions.
          </p>
          <button className="btn-primary" onClick={makeReport} disabled={busy}>
            Generate & download PDF
          </button>
          <ul className="text-sm space-y-2">
            {reports.map((r) => (
              <li key={r.id} className="flex gap-3 items-center">
                <span>Report #{r.id}</span>
                <button
                  className="text-pine underline"
                  onClick={async () => {
                    const token = getToken();
                    const res = await fetch(api.reportDownloadUrl(projectId, r.id), {
                      headers: { Authorization: `Bearer ${token}` },
                    });
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = `renovation-report-${projectId}-${r.id}.pdf`;
                    a.click();
                  }}
                >
                  Download
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function AuthImage({
  projectId,
  imageId,
  designId,
  kind = "original",
}: {
  projectId: number;
  imageId?: number;
  designId?: number;
  kind?: "original" | "redesign";
}) {
  const [src, setSrc] = useState<string>("");
  useEffect(() => {
    const token = getToken();
    const url =
      kind === "redesign" && designId
        ? api.redesignUrl(projectId, designId)
        : api.imageUrl(projectId, imageId!);
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((b) => setSrc(URL.createObjectURL(b)))
      .catch(() => setSrc(""));
  }, [projectId, imageId, designId, kind]);
  if (!src) return <div className="h-48 bg-mist rounded-xl animate-pulse" />;
  return <img src={src} alt={kind} className="rounded-xl max-h-96 w-full object-contain border border-mist bg-white" />;
}
