"use client";

import { useEffect, useState } from "react";
import { Stage, Layer, Image as KonvaImage, Line, Circle, Text } from "react-konva";
import { api, getToken } from "@/lib/api";

const COLORS: Record<string, string> = {
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

const REGION_TYPES = Object.keys(COLORS);

export default function RegionCanvas({
  projectId,
  imageId,
  regions,
  onChange,
}: {
  projectId: number;
  imageId: number;
  regions: any[];
  onChange: (regions: any[]) => void;
}) {
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [mode, setMode] = useState<"select" | "draw">("select");
  const [drawType, setDrawType] = useState("main_wall");
  const [draft, setDraft] = useState<{ x: number; y: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const width = 720;
  const [height, setHeight] = useState(480);

  useEffect(() => {
    const token = getToken();
    fetch(api.imageUrl(projectId, imageId), {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const img = new window.Image();
        img.onload = () => {
          const h = Math.round((img.height / img.width) * width);
          setHeight(h);
          setImage(img);
        };
        img.src = url;
      });
  }, [projectId, imageId]);

  async function saveLabel(region: any, label: string) {
    const updated = await api.updateRegion(projectId, region.id, {
      label,
      points: region.points,
      user_corrected: true,
    });
    onChange(regions.map((r) => (r.id === region.id ? updated : r)));
  }

  async function removeRegion(id: number) {
    await api.deleteRegion(projectId, id);
    onChange(regions.filter((r) => r.id !== id));
    if (selected === id) setSelected(null);
  }

  async function persistPoints(regionId: number, points: { x: number; y: number }[]) {
    setBusy(true);
    try {
      const updated = await api.updateRegion(projectId, regionId, {
        points,
        user_corrected: true,
      });
      onChange(regions.map((r) => (r.id === regionId ? updated : r)));
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

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 items-center">
        <button
          type="button"
          className={mode === "select" ? "btn-primary text-sm py-1.5" : "btn-ghost text-sm py-1.5"}
          onClick={() => {
            setMode("select");
            setDraft([]);
          }}
        >
          Select / resize
        </button>
        <button
          type="button"
          className={mode === "draw" ? "btn-primary text-sm py-1.5" : "btn-ghost text-sm py-1.5"}
          onClick={() => setMode("draw")}
        >
          Draw new region
        </button>
        {mode === "draw" && (
          <>
            <select className="input w-44 py-1.5" value={drawType} onChange={(e) => setDrawType(e.target.value)}>
              {REGION_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <button type="button" className="btn-secondary text-sm py-1.5" disabled={draft.length < 3 || busy} onClick={finishDraw}>
              Finish polygon ({draft.length} pts)
            </button>
            <button type="button" className="btn-ghost text-sm py-1.5" onClick={() => setDraft([])}>
              Clear draft
            </button>
          </>
        )}
      </div>

      <div className="overflow-auto border border-mist rounded-xl bg-white">
        <Stage width={width} height={height} onClick={onStageClick}>
          <Layer>
            {image && <KonvaImage image={image} width={width} height={height} listening={mode === "draw"} />}
            {regions.map((r) => {
              const flat = (r.points || []).flatMap((p: any) => [p.x * width, p.y * height]);
              return (
                <Line
                  key={r.id}
                  points={flat}
                  closed
                  stroke={COLORS[r.region_type] || "#333"}
                  strokeWidth={selected === r.id ? 3 : 2}
                  fill={(COLORS[r.region_type] || "#333") + "33"}
                  onClick={(evt) => {
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
                <Text
                  key={`t-${r.id}`}
                  x={p0.x * width}
                  y={p0.y * height - 14}
                  text={r.label || r.region_type}
                  fontSize={12}
                  fill="#1a2332"
                />
              );
            })}
            {mode === "select" &&
              selectedRegion?.points?.map((p: any, idx: number) => (
                <Circle
                  key={`h-${selectedRegion.id}-${idx}`}
                  x={p.x * width}
                  y={p.y * height}
                  radius={6}
                  fill="#c45c26"
                  stroke="#fff"
                  strokeWidth={1}
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
                stroke="#c45c26"
                strokeWidth={2}
                dash={[6, 4]}
              />
            )}
            {draft.map((p, i) => (
              <Circle key={`d-${i}`} x={p.x * width} y={p.y * height} radius={4} fill="#c45c26" />
            ))}
          </Layer>
        </Stage>
      </div>

      <div className="grid md:grid-cols-2 gap-2">
        {regions.map((r) => (
          <div
            key={r.id}
            className={`flex gap-2 items-center text-sm rounded-lg px-3 py-2 ${
              selected === r.id ? "bg-pine/15 border border-pine/40" : "bg-mist/40"
            }`}
          >
            <button type="button" className="min-w-[100px] font-semibold text-left" onClick={() => setSelected(r.id)}>
              {r.region_type}
            </button>
            <input
              className="input py-1"
              defaultValue={r.label || ""}
              onBlur={(e) => saveLabel(r, e.target.value)}
            />
            <button type="button" className="text-clay" onClick={() => removeRegion(r.id)}>
              Delete
            </button>
          </div>
        ))}
      </div>
      <p className="text-xs text-slate">
        Select mode: click a polygon, drag orange handles to resize. Draw mode: click corners, then Finish polygon.
        {busy ? " Saving…" : ""}
      </p>
    </div>
  );
}
