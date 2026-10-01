"use client";

import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { Stage, Layer, Image as KonvaImage, Line, Circle, Label, Tag, Text } from "react-konva";
import { api, getToken } from "@/lib/api";
import { Icon } from "@/components/icons";
import { useToast } from "@/components/Toast";
import { humanize, Spinner } from "@/components/ui";

export const REGION_COLORS: Record<string, string> = {
  main_wall: "#2f6f5e",
  window: "#3b82f6",
  balcony: "#c45c26",
  pillar: "#7c3aed",
  parapet: "#0f766e",
  gate: "#b45309",
  roof_edge: "#334155",
  railing: "#db2777",
  other: "#64748b",
};

const REGION_TYPES = Object.keys(REGION_COLORS);
const MAX_WIDTH = 960;

export default function RegionCanvas({
  projectId,
  imageId,
  regions,
  onChange,
  onClearAll,
}: {
  projectId: number;
  imageId: number;
  regions: any[];
  onChange: (regions: any[]) => void;
  onClearAll?: () => void;
}) {
  const toast = useToast();
  const containerRef = useRef<HTMLDivElement>(null);
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [imageError, setImageError] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [mode, setMode] = useState<"select" | "draw">("select");
  const [drawType, setDrawType] = useState("main_wall");
  const [draft, setDraft] = useState<{ x: number; y: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  // Points are stored normalized (0–1), so the stage can scale to the container width.
  const [width, setWidth] = useState(720);
  const [aspect, setAspect] = useState(2 / 3);
  const height = Math.round(width * aspect);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setWidth(Math.max(240, Math.min(MAX_WIDTH, Math.floor(el.clientWidth))));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const token = getToken();
    let objectUrl = "";
    setImageError(false);
    fetch(api.imageUrl(projectId, imageId), {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => {
        if (!r.ok) throw new Error();
        return r.blob();
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        const img = new window.Image();
        img.onload = () => {
          setAspect(img.height / img.width);
          setImage(img);
        };
        img.src = objectUrl;
      })
      .catch(() => setImageError(true));
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [projectId, imageId]);

  async function saveLabel(region: any, label: string) {
    if ((region.label || "") === label) return;
    try {
      const updated = await api.updateRegion(projectId, region.id, {
        label,
        points: region.points,
        user_corrected: true,
      });
      onChange(regions.map((r) => (r.id === region.id ? updated : r)));
      toast.success("Region label saved");
    } catch (err: any) {
      toast.error(err.message);
    }
  }

  async function removeRegion(id: number) {
    try {
      await api.deleteRegion(projectId, id);
      onChange(regions.filter((r) => r.id !== id));
      if (selected === id) setSelected(null);
      toast.success("Region deleted");
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setConfirmDelete(null);
    }
  }

  async function persistPoints(regionId: number, points: { x: number; y: number }[]) {
    setBusy(true);
    try {
      const updated = await api.updateRegion(projectId, regionId, {
        points,
        user_corrected: true,
      });
      onChange(regions.map((r) => (r.id === regionId ? updated : r)));
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function finishDraw() {
    if (draft.length < 3) return;
    setBusy(true);
    try {
      const created = await api.createRegion(projectId, {
        region_type: drawType,
        label: `Custom ${drawType}`,
        points: draft,
        user_corrected: true,
      });
      onChange([...regions, created]);
      setDraft([]);
      setMode("select");
      setSelected(created.id);
      toast.success(`${humanize(drawType)} region added`);
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  function onStageClick(e: any) {
    if (mode !== "draw") return;
    const stage = e.target.getStage();
    const pos = stage.getPointerPosition();
    if (!pos) return;
    setDraft((d) => [...d, { x: pos.x / width, y: pos.y / height }]);
  }

  const selectedRegion = regions.find((r) => r.id === selected);
  const presentTypes = Array.from(new Set(regions.map((r) => r.region_type)));

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-slate-50 p-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="inline-flex rounded-lg bg-white p-1 shadow-sm ring-1 ring-slate-200" role="group" aria-label="Editing mode">
          <button
            type="button"
            aria-pressed={mode === "select"}
            className={clsx(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              mode === "select" ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100"
            )}
            onClick={() => {
              setMode("select");
              setDraft([]);
            }}
          >
            <Icon name="cursor" /> Select & adjust
          </button>
          <button
            type="button"
            aria-pressed={mode === "draw"}
            className={clsx(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              mode === "draw" ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100"
            )}
            onClick={() => setMode("draw")}
          >
            <Icon name="polygon" /> Draw region
          </button>
        </div>
        {mode === "draw" && (
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="draw-type" className="sr-only">
              Region type to draw
            </label>
            <select id="draw-type" className="input w-40 py-1.5" value={drawType} onChange={(e) => setDrawType(e.target.value)}>
              {REGION_TYPES.map((t) => (
                <option key={t} value={t}>
                  {humanize(t)}
                </option>
              ))}
            </select>
            <button type="button" className="btn-ghost btn-sm" onClick={() => setDraft([])} disabled={!draft.length}>
              Clear draft
            </button>
            <button type="button" className="btn-primary btn-sm" disabled={draft.length < 3 || busy} onClick={finishDraw}>
              {busy ? <Spinner /> : <Icon name="check" />} Finish ({draft.length} pts)
            </button>
          </div>
        )}
        {mode === "select" && regions.length > 0 && onClearAll && (
          <button type="button" className="btn-outline btn-sm" onClick={onClearAll} disabled={busy}>
            <Icon name="trash" className="h-3.5 w-3.5" /> Clear all
          </button>
        )}
        {mode === "select" && busy && (
          <span className="flex items-center gap-2 px-2 text-xs text-slate-500">
            <Spinner className="h-3.5 w-3.5" /> Saving…
          </span>
        )}
      </div>

      <p className="text-xs text-slate-500">
        {mode === "select"
          ? "Click a shape to select it, then drag the orange handles to reshape it."
          : "Click on the photo to place corners. Add at least 3 points, then press Finish."}
      </p>

      {/* Canvas */}
      <div ref={containerRef} className="w-full">
        <div
          className={clsx(
            "relative mx-auto overflow-hidden rounded-xl border border-slate-200 bg-slate-100",
            mode === "draw" && "cursor-crosshair"
          )}
          style={{ width, height }}
        >
          {!image && (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-slate-500">
              {imageError ? "Couldn't load the photo." : (
                <span className="flex items-center gap-2">
                  <Spinner /> Loading photo…
                </span>
              )}
            </div>
          )}
          <Stage width={width} height={height} onClick={onStageClick} onTap={onStageClick}>
            <Layer>
              {image && <KonvaImage image={image} width={width} height={height} listening={mode === "draw"} />}
              {regions.map((r) => {
                const flat = (r.points || []).flatMap((p: any) => [p.x * width, p.y * height]);
                const color = REGION_COLORS[r.region_type] || "#333333";
                return (
                  <Line
                    key={r.id}
                    points={flat}
                    closed
                    stroke={color}
                    strokeWidth={selected === r.id ? 3 : 2}
                    fill={color + (selected === r.id ? "55" : "33")}
                    onClick={(evt) => {
                      if (mode !== "select") return;
                      evt.cancelBubble = true;
                      setSelected(r.id);
                    }}
                    onTap={(evt) => {
                      if (mode !== "select") return;
                      evt.cancelBubble = true;
                      setSelected(r.id);
                    }}
                  />
                );
              })}
              {regions.map((r) => {
                const p0 = r.points?.[0];
                if (!p0) return null;
                return (
                  <Label key={`t-${r.id}`} x={p0.x * width} y={Math.max(0, p0.y * height - 18)} listening={false}>
                    <Tag fill={REGION_COLORS[r.region_type] || "#333333"} cornerRadius={3} opacity={0.9} />
                    <Text text={r.label || humanize(r.region_type)} fontSize={11} padding={3} fill="#ffffff" />
                  </Label>
                );
              })}
              {mode === "select" &&
                selectedRegion?.points?.map((p: any, idx: number) => (
                  <Circle
                    key={`h-${selectedRegion.id}-${idx}`}
                    x={p.x * width}
                    y={p.y * height}
                    radius={7}
                    fill="#d06a33"
                    stroke="#fff"
                    strokeWidth={2}
                    draggable
                    onDragEnd={async (e) => {
                      const nx = Math.min(1, Math.max(0, e.target.x() / width));
                      const ny = Math.min(1, Math.max(0, e.target.y() / height));
                      const next = selectedRegion.points.map((pt: any, i: number) =>
                        i === idx ? { x: nx, y: ny } : pt
                      );
                      await persistPoints(selectedRegion.id, next);
                    }}
                  />
                ))}
              {draft.length > 0 && (
                <Line
                  points={draft.flatMap((p) => [p.x * width, p.y * height])}
                  closed={false}
                  stroke="#d06a33"
                  strokeWidth={2}
                  dash={[6, 4]}
                />
              )}
              {draft.map((p, i) => (
                <Circle key={`d-${i}`} x={p.x * width} y={p.y * height} radius={5} fill="#d06a33" stroke="#fff" strokeWidth={1.5} />
              ))}
            </Layer>
          </Stage>
        </div>
      </div>

      {presentTypes.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-slate-600" aria-label="Legend">
          {presentTypes.map((t) => (
            <span key={t} className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: REGION_COLORS[t] || "#333" }} />
              {humanize(t)}
            </span>
          ))}
        </div>
      )}

      {/* Region list */}
      {regions.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-900">
            Regions <span className="font-normal text-slate-500">({regions.length})</span>
          </h3>
          <ul className="grid gap-2 md:grid-cols-2">
            {regions.map((r) => (
              <li
                key={r.id}
                className={clsx(
                  "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors",
                  selected === r.id ? "border-brand-300 bg-brand-50" : "border-slate-200 bg-white"
                )}
              >
                <button
                  type="button"
                  className="flex min-w-[7.5rem] items-center gap-2 text-left font-medium text-slate-800"
                  onClick={() => {
                    setMode("select");
                    setSelected(r.id);
                  }}
                  aria-pressed={selected === r.id}
                >
                  <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: REGION_COLORS[r.region_type] || "#333" }} />
                  {humanize(r.region_type)}
                </button>
                <input
                  className="input py-1"
                  aria-label={`Label for ${humanize(r.region_type)} region`}
                  placeholder="Label"
                  defaultValue={r.label || ""}
                  onBlur={(e) => saveLabel(r, e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                />
                {confirmDelete === r.id ? (
                  <span className="flex shrink-0 items-center gap-1">
                    <button type="button" className="btn-danger btn-sm" onClick={() => removeRegion(r.id)}>
                      Delete
                    </button>
                    <button type="button" className="btn-ghost btn-sm" onClick={() => setConfirmDelete(null)}>
                      Keep
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="btn-icon h-8 w-8 shrink-0 hover:bg-red-50 hover:text-red-600"
                    aria-label={`Delete ${humanize(r.region_type)} region`}
                    onClick={() => setConfirmDelete(r.id)}
                  >
                    <Icon name="trash" />
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
