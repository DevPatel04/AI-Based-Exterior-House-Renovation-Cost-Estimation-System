"use client";

import clsx from "clsx";
import dynamic from "next/dynamic";
import Link from "next/link";
import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { api, downloadAuthed, getToken } from "@/lib/api";
import { Icon, IconName } from "@/components/icons";
import { useToast } from "@/components/Toast";
import {
  Alert,
  Badge,
  EmptyState,
  Field,
  formatDate,
  formatINR,
  formatNumber,
  humanize,
  Modal,
  Spinner,
  Stat,
  StatusBadge,
} from "@/components/ui";

const RegionCanvas = dynamic(() => import("@/components/RegionCanvas"), {
  ssr: false,
  loading: () => <div className="skeleton h-80 w-full" />,
});
const ImageCropper = dynamic(() => import("@/components/ImageCropper"), { ssr: false });

const STEPS: { label: string; icon: IconName; blurb: string }[] = [
  { label: "Upload", icon: "upload", blurb: "Add a clear exterior photo" },
  { label: "Regions", icon: "layers", blurb: "Review detected areas" },
  { label: "Materials", icon: "palette", blurb: "Choose finishes per region" },
  { label: "Visualize", icon: "sparkles", blurb: "Generate the redesign" },
  { label: "Estimate", icon: "calculator", blurb: "Areas, quantities & costs" },
  { label: "Report", icon: "file", blurb: "Download the PDF" },
];

export default function ProjectWorkspacePage() {
  const params = useParams();
  const projectId = Number(params.id);
  const toast = useToast();
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
  const [shareOpen, setShareOpen] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [members, setMembers] = useState<any[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [pendingCrop, setPendingCrop] = useState<File | null>(null);
  const [lastQuality, setLastQuality] = useState<{ ok: boolean; message: string } | null>(null);
  const [newDesignName, setNewDesignName] = useState("Design B");
  const [facadeWidth, setFacadeWidth] = useState("30");
  const [facadeHeight, setFacadeHeight] = useState("22");
  const [user, setUser] = useState<any>(null);
  const [redesignVersion, setRedesignVersion] = useState(0);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const stepperRef = useRef<HTMLElement>(null);
  const firstStepRender = useRef(true);

  // On step change: keep the active step visible in the (mobile) horizontal stepper and bring the
  // top of the new step into view if the user continued from further down the page.
  useEffect(() => {
    if (firstStepRender.current) {
      firstStepRender.current = false;
      return;
    }
    const nav = stepperRef.current;
    if (!nav) return;
    const active = nav.querySelector<HTMLElement>("[aria-current=step]");
    if (active && nav.scrollWidth > nav.clientWidth) {
      nav.scrollTo({ left: active.offsetLeft - (nav.clientWidth - active.offsetWidth) / 2, behavior: "smooth" });
    }
    const top = nav.getBoundingClientRect().top;
    if (top < 64) window.scrollTo({ top: window.scrollY + top - 88, behavior: "smooth" });
  }, [step]);

  const primary = images.find((i) => i.is_primary) || images[0];
  const activeDesign = designs.find((d) => d.id === activeDesignId) || designs.find((d) => d.is_active);

  const roles = useMemo<string[]>(() => user?.roles?.map((r: any) => r.name) || [], [user]);
  const hasRole = (...r: string[]) => r.some((x) => roles.includes(x));
  const canOverrideArea = hasRole("contractor", "architect", "builder", "admin");
  const canEditQuantity = hasRole("contractor", "builder", "admin");
  const canEditRates = hasRole("homeowner", "contractor", "builder", "admin");

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
    refresh().catch((e) => setLoadError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  function chooseFile(file?: File | null) {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toast.error("Please choose an image file.");
      return;
    }
    setLastQuality(null);
    setPendingCrop(file);
  }

  async function uploadCropped(file: File, setPrimary = true) {
    setBusy(true);
    setProgress("Uploading photo…");
    setPendingCrop(null);
    try {
      const img = await api.uploadImage(projectId, file, setPrimary);
      setLastQuality({ ok: true, message: img.quality_message || "Uploaded" });
      await refresh();
      toast.success("Photo uploaded.");
      setStep(1);
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setBusy(false);
      setProgress("");
    }
  }

  async function setPrimaryImage(imageId: number) {
    setBusy(true);
    setProgress("Updating primary photo…");
    try {
      await api.setPrimaryImage(projectId, imageId);
      await refresh();
      toast.success("Primary photo updated.");
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setBusy(false);
      setProgress("");
    }
  }

  // Long-running actions below only run from their own step, so they don't call setStep on
  // completion — that would pull the user back if they navigated elsewhere meanwhile.
  async function detect() {
    if (regions.length) {
      const ok = window.confirm(
        "Re-detect will replace auto-detected regions. Manually edited regions are kept. Continue?"
      );
      if (!ok) return;
    }
    setBusy(true);
    setProgress("Detecting with SegFormer (masks)… this can take ~15–60s.");
    try {
      const regs = await api.detectRegions(projectId);
      setRegions(regs);
      const alive = new Set(regs.map((r: any) => r.id));
      setAssignments((prev) => {
        const next: Record<number, number> = {};
        for (const [rid, mid] of Object.entries(prev)) {
          if (alive.has(Number(rid))) next[Number(rid)] = mid;
        }
        return next;
      });
      toast.success(`SegFormer detected ${regs.length} regions. Drag handles to fine-tune.`);
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setBusy(false);
      setProgress("");
    }
  }

  async function ensureDesign() {
    if (activeDesignId) return activeDesignId;
    const d = await api.createDesign(projectId, "Design A");
    setDesigns((prev) => [d, ...prev]);
    setActiveDesignId(d.id);
    return d.id as number;
  }

  function buildAssignmentItems(): { region_id: number; material_id: number }[] | null {
    const regionIds = new Set(regions.map((r) => r.id));
    const materialById = new Map(materials.map((m) => [m.id, m]));
    const staleRegions: number[] = [];
    const badMaterials: { id: number; regionId: number }[] = [];
    const items = Object.entries(assignments)
      .filter(([, material_id]) => Number(material_id) > 0)
      .map(([region_id, material_id]) => ({
        region_id: Number(region_id),
        material_id: Number(material_id),
      }))
      .filter((item) => {
        if (!regionIds.has(item.region_id)) {
          staleRegions.push(item.region_id);
          return false;
        }
        if (!materialById.has(item.material_id)) {
          badMaterials.push({ id: item.material_id, regionId: item.region_id });
          return false;
        }
        return true;
      });
    if (staleRegions.length || badMaterials.length) {
      const parts: string[] = [];
      if (staleRegions.length) {
        parts.push(
          `Wrong region id(s): ${staleRegions.join(", ")} (re-detect replaced them — re-select materials)`
        );
      }
      if (badMaterials.length) {
        parts.push(
          `Wrong material id(s): ${badMaterials
            .map((b) => `${b.id} (for region ${b.regionId})`)
            .join(", ")}`
        );
      }
      toast.error(parts.join(". "));
      return null;
    }
    if (!items.length) {
      toast.error("Select at least one material before saving.");
      return null;
    }
    return items;
  }

  async function saveAssignments() {
    setBusy(true);
    setProgress("Saving materials…");
    try {
      const designId = await ensureDesign();
      const items = buildAssignmentItems();
      if (!items) return;
      await api.assignMaterials(projectId, designId, items);
      await api.activateDesign(projectId, designId);
      await refresh();
      toast.success("Materials saved on design.");
      setStep(3);
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setBusy(false);
      setProgress("");
    }
  }

  async function runVisualize(hq = false) {
    setBusy(true);
    setProgress(hq ? "Generating high-quality redesign (Gemini)…" : "Generating redesign…");
    try {
      const designId = await ensureDesign();
      // Persist current assignments onto this design so Design B (etc.) gets its own materials/prompt
      const items = buildAssignmentItems();
      if (!items) {
        setStep(2);
        return;
      }
      await api.assignMaterials(projectId, designId, items);
      await api.activateDesign(projectId, designId);
      await api.visualize(projectId, designId, hq);
      await refresh();
      setRedesignVersion((v) => v + 1);
      toast.success(hq ? "HQ redesign generated." : "Redesign generated.");
    } catch (err: any) {
      toast.error(err.message || "Redesign failed");
    } finally {
      setBusy(false);
      setProgress("");
    }
  }

  async function switchDesign(designId: number) {
    setBusy(true);
    setProgress("Switching design…");
    try {
      await api.activateDesign(projectId, designId);
      setActiveDesignId(designId);
      const map = await api.getDesignMaterials(projectId, designId);
      const obj: Record<number, number> = {};
      map.forEach((m: any) => {
        obj[m.region_id] = m.material_id;
      });
      setAssignments(obj);
      await refresh();
      toast.success("Active design switched.");
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setBusy(false);
      setProgress("");
    }
  }

  async function addDesignVariant() {
    setBusy(true);
    try {
      const d = await api.createDesign(projectId, newDesignName || `Design ${designs.length + 1}`);
      setDesigns((prev) => [d, ...prev]);
      setActiveDesignId(d.id);
      // Keep current material picks as a starting point for the new variant (user can change them)
      toast.success(`Created ${d.name}. Adjust materials if needed, save, then generate its redesign.`);
      setStep(2);
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function runEstimate(e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setProgress("Calculating areas, quantities and costs…");
    try {
      const a = await api.estimateAreas(projectId, {
        known_width_ft: Number(facadeWidth) || 30,
        known_height_ft: Number(facadeHeight) || 22,
      });
      setAreas(a);
      const c = await api.calculate(projectId);
      setCosts(c);
      setQuantities(await api.listQuantities(projectId));
      await refresh();
      toast.success("Areas, quantities, and costs calculated.");
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setBusy(false);
      setProgress("");
    }
  }

  async function overrideArea(a: any, value: number) {
    setBusy(true);
    setProgress("Saving area override…");
    try {
      await api.overrideArea(projectId, {
        region_id: a.region_id,
        region_type: a.region_type,
        area_sq_ft: value,
        length_ft: a.length_ft,
        notes: "user override",
      });
      setAreas(await api.listAreas(projectId));
      const c = await api.calculate(projectId);
      setCosts(c);
      setQuantities(await api.listQuantities(projectId));
      toast.success("Area overridden and costs recalculated.");
    } catch (err: any) {
      toast.error(err.message);
      throw err;
    } finally {
      setBusy(false);
      setProgress("");
    }
  }

  async function overrideQuantity(q: any, value: number) {
    try {
      await api.overrideQuantity(projectId, {
        quantity_line_id: q.id,
        final_quantity: value,
      });
      setQuantities(await api.listQuantities(projectId));
      setCosts(await api.getCosts(projectId));
      toast.success("Quantity updated.");
    } catch (err: any) {
      toast.error(err.message);
      throw err;
    }
  }

  async function updateRate(line: any, field: "material_rate" | "labor_rate", raw: string) {
    if (!line.material_id) return;
    const value = Number(raw);
    if (!Number.isFinite(value) || value === Number(line[field])) return;
    try {
      await api.setRates(projectId, { material_id: line.material_id, [field]: value });
      setCosts(await api.getCosts(projectId));
      toast.success(`${field === "material_rate" ? "Material" : "Labor"} rate updated.`);
    } catch (err: any) {
      toast.error(err.message);
    }
  }

  async function downloadReport(reportId: number, filename: string) {
    setDownloadingId(reportId);
    try {
      await downloadAuthed(api.reportDownloadUrl(projectId, reportId), filename);
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setDownloadingId(null);
    }
  }

  async function makeReport() {
    setBusy(true);
    setProgress("Generating PDF report…");
    try {
      const designId = activeDesign?.id;
      const r = await api.createReport(projectId, designId);
      setReports(await api.listReports(projectId));
      // Download with the auth header (the endpoint requires a bearer token).
      await downloadAuthed(api.reportDownloadUrl(projectId, r.id), `renovation-report-${projectId}.pdf`);
      toast.success("Report generated and downloaded.");
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setBusy(false);
      setProgress("");
    }
  }

  function openShare() {
    setShareOpen(true);
    setMembers(null);
    api
      .listMembers(projectId)
      .then(setMembers)
      .catch(() => setMembers([]));
  }

  async function share(e: FormEvent) {
    e.preventDefault();
    setSharing(true);
    try {
      await api.shareProject(projectId, { user_email: shareEmail, member_role: "editor" });
      toast.success(`Shared with ${shareEmail}`);
      setShareEmail("");
      api.listMembers(projectId).then(setMembers).catch(() => {});
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setSharing(false);
    }
  }

  if (!project) {
    return loadError ? (
      <div className="mx-auto max-w-lg space-y-4 py-10">
        <Alert tone="error" title="Couldn't open this project">
          {loadError}
        </Alert>
        <Link href="/dashboard" className="btn-outline">
          <Icon name="chevronLeft" /> Back to projects
        </Link>
      </div>
    ) : (
      <div className="space-y-6">
        <div className="skeleton h-5 w-32" />
        <div className="skeleton h-9 w-72" />
        <div className="skeleton h-16 w-full" />
        <div className="skeleton h-96 w-full" />
      </div>
    );
  }

  const assignedCount = regions.filter((r) => assignments[r.id]).length;
  const done = [
    images.length > 0,
    regions.length > 0,
    assignedCount > 0,
    !!activeDesign?.redesign_path,
    !!costs?.lines?.length,
    reports.length > 0,
  ];

  const nav = (prev?: boolean, next?: ReactNode) => (
    <StepFooter
      onBack={prev && step > 0 ? () => setStep(step - 1) : undefined}
      backLabel={step > 0 ? STEPS[step - 1].label : undefined}
    >
      {next}
    </StepFooter>
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <nav aria-label="Breadcrumb" className="mb-2 flex items-center gap-1 text-sm text-slate-500">
            <Link href="/dashboard" className="hover:text-slate-900">
              Projects
            </Link>
            <Icon name="chevronRight" className="h-3.5 w-3.5" />
            <span className="truncate text-slate-700">{project.title}</span>
          </nav>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold text-slate-900 sm:text-3xl">{project.title}</h1>
            <StatusBadge status={project.status} />
          </div>
          {project.description && <p className="mt-1.5 max-w-3xl text-sm text-slate-600 sm:text-base">{project.description}</p>}
        </div>
        <div className="flex gap-2">
          <button className="btn-outline" onClick={openShare}>
            <Icon name="share" /> Share
          </button>
        </div>
      </div>

      {/* Stepper */}
      <nav ref={stepperRef} aria-label="Project steps" className="relative -mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <ol className="flex min-w-max gap-2 sm:grid sm:min-w-0 sm:grid-cols-3 lg:grid-cols-6">
          {STEPS.map((s, idx) => {
            const current = step === idx;
            return (
              <li key={s.label}>
                <button
                  type="button"
                  onClick={() => setStep(idx)}
                  aria-current={current ? "step" : undefined}
                  className={clsx(
                    "flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors",
                    current
                      ? "border-brand-500 bg-white shadow-card ring-1 ring-brand-500"
                      : "border-slate-200 bg-white/60 hover:border-slate-300 hover:bg-white"
                  )}
                >
                  <span
                    className={clsx(
                      "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                      current
                        ? "bg-brand-600 text-white"
                        : done[idx]
                          ? "bg-brand-100 text-brand-700"
                          : "bg-slate-100 text-slate-500"
                    )}
                  >
                    {done[idx] && !current ? <Icon name="check" className="h-4 w-4" /> : idx + 1}
                  </span>
                  <span className="min-w-0">
                    <span className={clsx("block text-sm font-semibold", current ? "text-slate-900" : "text-slate-700")}>
                      {s.label}
                    </span>
                    <span className="block truncate text-xs text-slate-500">{s.blurb}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </nav>

      {(busy || progress) && (
        <div
          role="status"
          className="sticky top-20 z-30 flex items-center gap-3 rounded-xl border border-brand-200 bg-brand-50/95 px-4 py-3 text-sm font-medium text-brand-800 shadow-card backdrop-blur"
        >
          <Spinner className="h-4 w-4 text-brand-600" />
          {progress || "Working…"}
        </div>
      )}

      {/* Step 1: Upload */}
      {step === 0 && (
        <StepCard
          title="Upload exterior photo"
          description="Upload any photo of the facade (JPG, PNG, WebP, and other common formats). Cropping is optional. Soft tips may appear, but uploads are never blocked by size."
        >
          {lastQuality && (
            <Alert
              tone={lastQuality.ok ? "success" : "warning"}
              title={lastQuality.ok ? "Photo looks good" : "This photo may not work well"}
              onDismiss={() => setLastQuality(null)}
            >
              {lastQuality.message}
              {!lastQuality.ok && " Try a brighter, sharper photo taken straight on."}
            </Alert>
          )}

          {pendingCrop ? (
            <ImageCropper file={pendingCrop} onCancel={() => setPendingCrop(null)} onCropped={(f) => uploadCropped(f, true)} />
          ) : (
            <label
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                chooseFile(e.dataTransfer.files?.[0]);
              }}
              className={clsx(
                "flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors",
                "focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-500/20",
                dragOver ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-slate-50 hover:border-brand-400 hover:bg-brand-50/40",
                busy && "pointer-events-none opacity-60"
              )}
            >
              <input
                type="file"
                accept="image/*"
                className="sr-only"
                disabled={busy}
                onChange={(e) => {
                  chooseFile(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white text-brand-600 shadow-sm ring-1 ring-slate-200">
                <Icon name="upload" className="h-5 w-5" />
              </span>
              <span className="mt-3 text-sm font-semibold text-slate-900">
                {images.length ? "Add another photo" : "Choose a photo"} <span className="font-normal text-slate-500">or drag it here</span>
              </span>
              <span className="mt-1 text-xs text-slate-500">Any common image format · optional crop next</span>
            </label>
          )}

          {images.length > 0 && (
            <div>
              <h3 className="mb-3 text-sm font-semibold text-slate-900">
                Uploaded photos <span className="font-normal text-slate-500">({images.length})</span>
              </h3>
              <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {images.map((img) => (
                  <li
                    key={img.id}
                    className={clsx(
                      "overflow-hidden rounded-xl border bg-white",
                      img.is_primary ? "border-brand-300 ring-1 ring-brand-300" : "border-slate-200"
                    )}
                  >
                    <AuthImage projectId={projectId} imageId={img.id} thumb />
                    <div className="space-y-2 p-3">
                      <div className="flex flex-wrap items-center gap-1.5">
                        {img.is_primary ? <Badge tone="brand">Primary</Badge> : <Badge>Extra angle</Badge>}
                        {img.quality_message && !img.quality_message.toLowerCase().includes("usable") && (
                          <Badge tone="neutral">Tip</Badge>
                        )}
                        {img.quality_message?.toLowerCase().includes("usable") && <Badge tone="success">Ready</Badge>}
                      </div>
                      {img.quality_message && <p className="line-clamp-2 text-xs text-slate-500">{img.quality_message}</p>}
                      {!img.is_primary && (
                        <button type="button" className="btn-outline btn-sm" onClick={() => setPrimaryImage(img.id)} disabled={busy}>
                          <Icon name="star" className="h-3.5 w-3.5" /> Set as primary
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {nav(
            false,
            <button className="btn-primary" onClick={() => setStep(1)} disabled={!primary}>
              Continue to regions <Icon name="arrowRight" />
            </button>
          )}
        </StepCard>
      )}

      {/* Step 2: Regions */}
      {step === 1 && (
        <StepCard
          title="Structure regions"
          description="Let AI outline walls, windows, balconies and more — then fine-tune any shape or draw your own."
          actions={
            <button className="btn-primary" onClick={detect} disabled={busy || !primary}>
              {busy && progress.startsWith("Detecting") ? <Spinner /> : <Icon name="wand" />}
              {regions.length ? "Re-detect with AI" : "Detect with AI"}
            </button>
          }
        >
          {primary ? (
            <>
              {regions.length === 0 && (
                <Alert tone="info">No regions yet. Click “Detect with AI” (SegFormer masks). Requires HF_TOKEN on the backend — or draw regions manually.</Alert>
              )}
              <RegionCanvas projectId={projectId} imageId={primary.id} regions={regions} onChange={setRegions} />
            </>
          ) : (
            <EmptyState
              icon="image"
              title="Upload a photo first"
              description="Regions are detected on your primary exterior photo."
              action={
                <button className="btn-primary" onClick={() => setStep(0)}>
                  Go to upload
                </button>
              }
            />
          )}
          {nav(
            true,
            <button className="btn-primary" onClick={() => setStep(2)}>
              Continue to materials <Icon name="arrowRight" />
            </button>
          )}
        </StepCard>
      )}

      {/* Step 3: Materials */}
      {step === 2 && (
        <StepCard
          title="Apply materials"
          description="Pick a finish for each region. Create design variants to compare options side by side."
        >
          <div className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4 lg:flex-row lg:items-end">
            <Field label="Design variant" className="lg:w-64">
              {(id) => (
                <select
                  id={id}
                  className="input"
                  value={activeDesignId || ""}
                  onChange={(e) => e.target.value && switchDesign(Number(e.target.value))}
                  disabled={busy}
                >
                  <option value="">Select design variant</option>
                  {designs.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                      {d.is_active ? " (active)" : ""}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <div className="hidden h-10 w-px bg-slate-200 lg:block" />
            <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-end">
              <Field label="New variant name" className="sm:w-56">
                {(id) => (
                  <input
                    id={id}
                    className="input"
                    value={newDesignName}
                    onChange={(e) => setNewDesignName(e.target.value)}
                    placeholder="e.g. Design B"
                  />
                )}
              </Field>
              <button type="button" className="btn-outline" onClick={addDesignVariant} disabled={busy}>
                <Icon name="plus" /> Add variant
              </button>
            </div>
          </div>

          {regions.length === 0 ? (
            <EmptyState
              icon="layers"
              title="No regions to assign"
              description="Detect or draw regions on your photo before choosing materials."
              action={
                <button className="btn-primary" onClick={() => setStep(1)}>
                  Go to regions
                </button>
              }
            />
          ) : (
            <div>
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900">Regions</h3>
                <Badge tone={assignedCount === regions.length ? "success" : "neutral"}>
                  {assignedCount} of {regions.length} assigned
                </Badge>
              </div>
              <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200">
                {regions.map((r) => {
                  const suited = materials.filter(
                    (m) =>
                      !m.suitable_regions?.length ||
                      m.suitable_regions.includes(r.region_type) ||
                      m.suitable_regions.includes("other")
                  );
                  const list = suited.length ? suited : materials;
                  const selectId = `material-${r.id}`;
                  return (
                    <li key={r.id} className="grid gap-2 bg-white p-4 md:grid-cols-[1fr_2fr] md:items-center md:gap-4">
                      <label htmlFor={selectId} className="min-w-0">
                        <span className="flex items-center gap-2 font-medium text-slate-900">
                          {assignments[r.id] ? (
                            <Icon name="checkCircle" className="h-4 w-4 shrink-0 text-emerald-500" />
                          ) : (
                            <span className="h-4 w-4 shrink-0 rounded-full border-2 border-slate-300" />
                          )}
                          <span className="truncate">{r.label || humanize(r.region_type)}</span>
                        </span>
                        <span className="ml-6 block text-xs text-slate-500">
                          {humanize(r.region_type)} · showing materials suited to this region
                        </span>
                      </label>
                      <select
                        id={selectId}
                        className="input"
                        value={assignments[r.id] || ""}
                        onChange={(e) => {
                          const v = e.target.value;
                          setAssignments((prev) => {
                            const next = { ...prev };
                            if (!v) delete next[r.id];
                            else next[r.id] = Number(v);
                            return next;
                          });
                        }}
                      >
                        <option value="">Select material</option>
                        {list.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name} ({humanize(m.material_type)}) — ₹{m.material_rate}/{m.unit}
                          </option>
                        ))}
                      </select>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {nav(
            true,
            <button className="btn-primary" onClick={saveAssignments} disabled={busy}>
              {busy && progress.startsWith("Saving") ? <Spinner /> : <Icon name="check" />}
              Save design & continue
            </button>
          )}
        </StepCard>
      )}

      {/* Step 4: Visualize */}
      {step === 3 && (
        <StepCard
          title="Renovation visualization"
          description={
            activeDesign
              ? `Generate a redesigned view using materials in “${activeDesign.name}”. Uses Replicate SDXL img2img from your photo (accurate facade). ControlNet / Cloudflare only if img2img fails.`
              : "Generate a redesigned view of your house using your selected materials."
          }
          actions={
            <>
              <button
                className="btn-outline"
                onClick={() => runVisualize(true)}
                disabled={busy}
                title="Stronger free render (more Cloudflare steps) — Gemini not required"
              >
                <Icon name="sparkles" /> HQ render
              </button>
              <button className="btn-primary" onClick={() => runVisualize(false)} disabled={busy}>
                {busy && progress.startsWith("Generating") ? <Spinner /> : <Icon name="wand" />}
                {activeDesign?.redesign_path ? "Regenerate" : "Generate redesign"}
              </button>
            </>
          }
        >
          <div className="grid gap-4 md:grid-cols-2">
            <figure>
              <figcaption className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-700">
                <Badge>Before</Badge> Original
              </figcaption>
              {primary ? (
                <AuthImage projectId={projectId} imageId={primary.id} />
              ) : (
                <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-slate-300 text-sm text-slate-500">
                  No photo uploaded
                </div>
              )}
            </figure>
            <figure>
              <figcaption className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-700">
                <Badge tone="brand">After</Badge> {activeDesign ? activeDesign.name : "Redesign"}
                {activeDesign?.hq_mode && <Badge tone="violet">HQ</Badge>}
                {activeDesign?.prompt_used?.includes("[replicate_img2img]") && (
                  <Badge tone="brand">Replicate img2img</Badge>
                )}
                {activeDesign?.prompt_used?.includes("[replicate_controlnet]") && (
                  <Badge tone="brand">Replicate ControlNet</Badge>
                )}
                {activeDesign?.prompt_used?.includes("[fal_controlnet]") && (
                  <Badge tone="brand">fal ControlNet</Badge>
                )}
                {activeDesign?.prompt_used?.includes("[gemini_hq]") && (
                  <Badge tone="violet">Gemini HQ</Badge>
                )}
                {activeDesign?.prompt_used?.includes("[hf_img2img]") && (
                  <Badge tone="neutral">Hugging Face</Badge>
                )}
                {activeDesign?.prompt_used?.includes("[cloudflare]") && (
                  <Badge tone="brand">Cloudflare (free)</Badge>
                )}
                {activeDesign?.prompt_used?.includes("[local_fallback]") && (
                  <Badge tone="warning">Local preview (not AI)</Badge>
                )}
              </figcaption>
              {activeDesign?.redesign_path ? (
                <AuthImage
                  key={`${activeDesign.id}-${redesignVersion}`}
                  projectId={projectId}
                  designId={activeDesign.id}
                  kind="redesign"
                  version={redesignVersion}
                />
              ) : (
                <div className="flex h-64 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-6 text-center text-sm text-slate-500">
                  <Icon name="sparkles" className="h-6 w-6 text-slate-400" />
                  Your redesign will appear here once generated.
                </div>
              )}
            </figure>
          </div>
          {nav(
            true,
            <button className="btn-primary" onClick={() => setStep(4)}>
              Continue to estimate <Icon name="arrowRight" />
            </button>
          )}
        </StepCard>
      )}

      {/* Step 5: Estimate */}
      {step === 4 && (
        <StepCard
          title="Area, quantity & cost"
          description="Enter the approximate facade size so detected regions can be scaled to real-world measurements."
        >
          <form onSubmit={runEstimate} className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <Field label="Facade width (ft)">
              {(id) => (
                <input
                  id={id}
                  className="input"
                  type="number"
                  min={0}
                  step="any"
                  inputMode="decimal"
                  value={facadeWidth}
                  onChange={(e) => setFacadeWidth(e.target.value)}
                  placeholder="30"
                />
              )}
            </Field>
            <Field label="Facade height (ft)">
              {(id) => (
                <input
                  id={id}
                  className="input"
                  type="number"
                  min={0}
                  step="any"
                  inputMode="decimal"
                  value={facadeHeight}
                  onChange={(e) => setFacadeHeight(e.target.value)}
                  placeholder="22"
                />
              )}
            </Field>
            <button className="btn-primary" disabled={busy}>
              {busy && progress.startsWith("Calculating") ? <Spinner /> : <Icon name="calculator" />}
              {costs?.lines?.length ? "Recalculate" : "Calculate"}
            </button>
          </form>

          {costs && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label="Material total" value={formatINR(costs.material_total)} />
              <Stat label="Labor total" value={formatINR(costs.labor_total)} />
              <Stat label="Grand total" value={formatINR(costs.grand_total)} emphasis />
            </div>
          )}

          {areas.length === 0 && quantities.length === 0 && !costs?.lines?.length ? (
            <EmptyState
              icon="calculator"
              title="No estimate yet"
              description="Enter the facade size above and press Calculate to see areas, quantities and costs."
            />
          ) : (
            <div className="grid gap-6 xl:grid-cols-2">
              <DataTable title="Areas" count={areas.length}>
                <thead>
                  <tr>
                    <th>Region</th>
                    <th className="text-right">Area (sq ft)</th>
                    <th className="text-right">Length (ft)</th>
                  </tr>
                </thead>
                <tbody>
                  {areas.map((a) => (
                    <tr key={a.id}>
                      <td>
                        <span className="font-medium text-slate-900">{humanize(a.region_type)}</span>
                        {a.user_override && (
                          <Badge tone="accent" className="ml-2">
                            Edited
                          </Badge>
                        )}
                      </td>
                      <td className="text-right tabular-nums">
                        {canOverrideArea ? (
                          <InlineNumberEdit
                            value={a.area_sq_ft}
                            label={`area for ${humanize(a.region_type)}`}
                            onSave={(v) => overrideArea(a, v)}
                          />
                        ) : (
                          formatNumber(a.area_sq_ft)
                        )}
                      </td>
                      <td className="text-right tabular-nums">{formatNumber(a.length_ft)}</td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>

              <DataTable title="Quantities" count={quantities.length}>
                <thead>
                  <tr>
                    <th>Category</th>
                    <th className="text-right">Final qty</th>
                    <th>Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {quantities.map((q) => (
                    <tr key={q.id}>
                      <td>
                        <span className="font-medium text-slate-900">{humanize(q.category)}</span>
                        {q.user_override && (
                          <Badge tone="accent" className="ml-2">
                            Edited
                          </Badge>
                        )}
                      </td>
                      <td className="text-right tabular-nums">
                        {canEditQuantity ? (
                          <InlineNumberEdit
                            value={q.final_quantity}
                            label={`quantity for ${humanize(q.category)}`}
                            onSave={(v) => overrideQuantity(q, v)}
                          />
                        ) : (
                          formatNumber(q.final_quantity)
                        )}
                      </td>
                      <td className="text-slate-500">{q.unit?.replace("_", " ")}</td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          )}

          {costs?.lines?.length > 0 && (
            <DataTable
              title="Cost breakdown"
              count={costs.lines.length}
              note={canEditRates ? "Edit a rate and click away to recalculate." : undefined}
            >
              <thead>
                <tr>
                  <th>Category</th>
                  <th className="text-right">Qty</th>
                  <th className="text-right">Material rate (₹)</th>
                  <th className="text-right">Labor rate (₹)</th>
                  <th className="text-right">Total</th>
                </tr>
              </thead>
              <tbody>
                {costs.lines.map((line: any) => (
                  <tr key={line.id}>
                    <td className="font-medium text-slate-900">{humanize(line.category)}</td>
                    <td className="text-right tabular-nums text-slate-500">
                      {formatNumber(line.quantity)} {line.unit?.replace("_", " ")}
                    </td>
                    <td className="text-right">
                      {canEditRates && line.material_id ? (
                        <RateInput
                          key={`m-${line.id}-${line.material_rate}`}
                          defaultValue={line.material_rate}
                          label={`Material rate for ${humanize(line.category)}`}
                          onCommit={(v) => updateRate(line, "material_rate", v)}
                        />
                      ) : (
                        <span className="tabular-nums">{formatNumber(line.material_rate)}</span>
                      )}
                    </td>
                    <td className="text-right">
                      {canEditRates && line.material_id ? (
                        <RateInput
                          key={`l-${line.id}-${line.labor_rate}`}
                          defaultValue={line.labor_rate}
                          label={`Labor rate for ${humanize(line.category)}`}
                          onCommit={(v) => updateRate(line, "labor_rate", v)}
                        />
                      ) : (
                        <span className="tabular-nums">{formatNumber(line.labor_rate)}</span>
                      )}
                    </td>
                    <td className="text-right font-semibold tabular-nums text-slate-900">{formatINR(line.total_cost)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-slate-50">
                  <td colSpan={4} className="px-4 py-3 text-right text-sm font-semibold text-slate-700">
                    Grand total
                  </td>
                  <td className="px-4 py-3 text-right text-base font-bold tabular-nums text-brand-800">
                    {formatINR(costs.grand_total)}
                  </td>
                </tr>
              </tfoot>
            </DataTable>
          )}

          {costs?.disclaimer && (
            <p className="flex items-start gap-2 text-xs text-slate-500">
              <Icon name="info" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {costs.disclaimer}
            </p>
          )}

          {nav(
            true,
            <button className="btn-primary" onClick={() => setStep(5)}>
              Continue to report <Icon name="arrowRight" />
            </button>
          )}
        </StepCard>
      )}

      {/* Step 6: Report */}
      {step === 5 && (
        <StepCard
          title="Downloadable report"
          description="A PDF with the original photo, redesign, materials, quantities and full cost breakdown — ready for contractor discussions."
        >
          <div className="flex flex-col items-start gap-4 rounded-xl border border-brand-200 bg-brand-50 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white text-brand-600 shadow-sm">
                <Icon name="file" className="h-5 w-5" />
              </span>
              <div>
                <p className="font-semibold text-slate-900">Generate a new report</p>
                <p className="text-sm text-slate-600">
                  {activeDesign ? `Uses the active design “${activeDesign.name}”.` : "Uses your current project data."}
                  {!costs?.lines?.length && " Tip: calculate an estimate first for a complete breakdown."}
                </p>
              </div>
            </div>
            <button className="btn-primary shrink-0" onClick={makeReport} disabled={busy}>
              {busy && progress.startsWith("Generating PDF") ? <Spinner /> : <Icon name="download" />}
              Generate & download PDF
            </button>
          </div>

          <div>
            <h3 className="mb-3 text-sm font-semibold text-slate-900">
              Previous reports <span className="font-normal text-slate-500">({reports.length})</span>
            </h3>
            {reports.length === 0 ? (
              <p className="rounded-xl border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500">
                No reports generated yet.
              </p>
            ) : (
              <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white">
                {reports.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-3 px-4 py-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <Icon name="file" className="h-5 w-5 shrink-0 text-slate-400" />
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-slate-900">Report #{r.id}</p>
                        {r.created_at && <p className="text-xs text-slate-500">{formatDate(r.created_at)}</p>}
                      </div>
                    </div>
                    <button
                      className="btn-outline btn-sm"
                      disabled={downloadingId === r.id}
                      onClick={() => downloadReport(r.id, `renovation-report-${projectId}-${r.id}.pdf`)}
                    >
                      {downloadingId === r.id ? <Spinner className="h-3.5 w-3.5" /> : <Icon name="download" className="h-3.5 w-3.5" />}
                      Download
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {nav(true)}
        </StepCard>
      )}

      {/* Share dialog */}
      <Modal
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        title="Share project"
        description="Invite a registered user by email. They'll get editor access to this project."
      >
        <form onSubmit={share} className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <Field label="Email address" className="flex-1">
            {(id) => (
              <input
                id={id}
                type="email"
                className="input"
                placeholder="colleague@example.com"
                value={shareEmail}
                onChange={(e) => setShareEmail(e.target.value)}
                required
              />
            )}
          </Field>
          <button className="btn-primary" disabled={sharing || !shareEmail}>
            {sharing ? <Spinner /> : <Icon name="share" />} Share
          </button>
        </form>
        <div className="mt-6">
          <h3 className="text-sm font-semibold text-slate-900">People with access</h3>
          {members === null ? (
            <div className="mt-3 space-y-2">
              <div className="skeleton h-10" />
              <div className="skeleton h-10" />
            </div>
          ) : members.length === 0 ? (
            <p className="mt-2 text-sm text-slate-500">Only the owner has access so far.</p>
          ) : (
            <ul className="mt-2 divide-y divide-slate-100">
              {members.map((m) => (
                <li key={m.id} className="flex items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-900">{m.full_name || m.email}</p>
                    {m.full_name && <p className="truncate text-xs text-slate-500">{m.email}</p>}
                  </div>
                  <Badge>{humanize(m.member_role)}</Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Modal>
    </div>
  );
}

/* ---------- Local building blocks ---------- */

function StepCard({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card-panel animate-fade-in">
      <div className="flex flex-col gap-4 border-b border-slate-100 px-5 py-5 sm:flex-row sm:items-start sm:justify-between sm:px-6">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-slate-900 sm:text-xl">{title}</h2>
          {description && <p className="mt-1 max-w-3xl text-sm text-slate-500">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
      </div>
      <div className="space-y-6 p-5 sm:p-6">{children}</div>
    </section>
  );
}

function StepFooter({
  onBack,
  backLabel,
  children,
}: {
  onBack?: () => void;
  backLabel?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col-reverse gap-2 border-t border-slate-100 pt-5 sm:flex-row sm:items-center sm:justify-between">
      {onBack ? (
        <button type="button" className="btn-ghost" onClick={onBack}>
          <Icon name="chevronLeft" /> Back{backLabel ? ` to ${backLabel.toLowerCase()}` : ""}
        </button>
      ) : (
        <span />
      )}
      {children}
    </div>
  );
}

function DataTable({
  title,
  count,
  note,
  children,
}: {
  title: string;
  count?: number;
  note?: string;
  children: ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-200 px-4 py-3">
        <h3 className="text-sm font-semibold text-slate-900">
          {title} {count !== undefined && <span className="font-normal text-slate-500">({count})</span>}
        </h3>
        {note && <p className="text-xs text-slate-500">{note}</p>}
      </div>
      <div className="overflow-x-auto">
        <table className="table">{children}</table>
      </div>
    </div>
  );
}

/** Replaces window.prompt() — shows the value with an edit affordance, then an inline input. */
function InlineNumberEdit({
  value,
  label,
  onSave,
}: {
  value: number;
  label: string;
  onSave: (value: number) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(value ?? ""));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(String(value ?? ""));
  }, [value, editing]);

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    const n = Number(draft);
    if (draft === "" || !Number.isFinite(n)) return;
    setSaving(true);
    try {
      await onSave(n);
      setEditing(false);
    } catch {
      /* error surfaced by caller; keep editor open */
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="group inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 tabular-nums hover:bg-slate-100"
        aria-label={`Edit ${label}`}
      >
        {formatNumber(value)}
        <Icon name="pencil" className="h-3.5 w-3.5 text-slate-400 group-hover:text-brand-600" />
      </button>
    );
  }
  return (
    <form onSubmit={submit} className="inline-flex items-center justify-end gap-1">
      <input
        autoFocus
        type="number"
        step="any"
        min={0}
        inputMode="decimal"
        aria-label={label}
        className="input w-24 py-1 text-right"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setEditing(false)}
        disabled={saving}
      />
      <button type="submit" className="btn-icon h-8 w-8 text-brand-600" aria-label="Save" disabled={saving}>
        {saving ? <Spinner /> : <Icon name="check" />}
      </button>
      <button type="button" className="btn-icon h-8 w-8" aria-label="Cancel" onClick={() => setEditing(false)} disabled={saving}>
        <Icon name="x" />
      </button>
    </form>
  );
}

function RateInput({
  defaultValue,
  label,
  onCommit,
}: {
  defaultValue: number;
  label: string;
  onCommit: (value: string) => void;
}) {
  return (
    <input
      type="number"
      step="any"
      min={0}
      inputMode="decimal"
      aria-label={label}
      className="input ml-auto w-28 py-1.5 text-right tabular-nums"
      defaultValue={defaultValue}
      onBlur={(e) => onCommit(e.target.value)}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

function AuthImage({
  projectId,
  imageId,
  designId,
  kind = "original",
  version = 0,
  thumb,
}: {
  projectId: number;
  imageId?: number;
  designId?: number;
  kind?: "original" | "redesign";
  version?: number;
  /** Fixed-height cover crop for thumbnails instead of the full contained image. */
  thumb?: boolean;
}) {
  const [src, setSrc] = useState<string>("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const token = getToken();
    const url =
      kind === "redesign" && designId
        ? api.redesignUrl(projectId, designId)
        : api.imageUrl(projectId, imageId!);
    let objectUrl = "";
    let cancelled = false;
    setFailed(false);
    fetch(url, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error();
        return r.blob();
      })
      .then((b) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(b);
        setSrc(objectUrl);
      })
      .catch(() => {
        if (cancelled) return;
        setSrc("");
        setFailed(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [projectId, imageId, designId, kind, version]);

  if (failed) {
    return (
      <div
        className={clsx(
          "flex items-center justify-center bg-slate-50 text-sm text-slate-500",
          thumb ? "h-44" : "h-48 rounded-xl border border-slate-200"
        )}
      >
        <Icon name="image" className="mr-2 h-4 w-4" /> Image unavailable
      </div>
    );
  }
  if (!src) return <div className={clsx("skeleton w-full", thumb ? "h-44 rounded-none" : "h-48 rounded-xl")} />;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={kind === "redesign" ? "Redesigned exterior" : "Original exterior photo"}
      className={
        thumb
          ? "h-44 w-full bg-slate-100 object-cover"
          : "max-h-[28rem] w-full rounded-xl border border-slate-200 bg-slate-50 object-contain"
      }
    />
  );
}
