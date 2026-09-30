"use client";

import { useEffect, useRef, useState } from "react";
import { Stage, Layer, Image as KonvaImage, Line, Text } from "react-konva";
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
  }

  return (
    <div className="space-y-3">
      <div className="overflow-auto border border-mist rounded-xl bg-white">
        <Stage width={width} height={height}>
          <Layer>
            {image && <KonvaImage image={image} width={width} height={height} />}
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
                  onClick={() => setSelected(r.id)}
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
          </Layer>
        </Stage>
      </div>
      <div className="grid md:grid-cols-2 gap-2">
        {regions.map((r) => (
          <div key={r.id} className="flex gap-2 items-center text-sm bg-mist/40 rounded-lg px-3 py-2">
            <span className="min-w-[100px] font-semibold">{r.region_type}</span>
            <input
              className="input py-1"
              defaultValue={r.label || ""}
              onBlur={(e) => saveLabel(r, e.target.value)}
            />
            <button className="text-clay" onClick={() => removeRegion(r.id)}>
              Delete
            </button>
          </div>
        ))}
      </div>
      <p className="text-xs text-slate">
        Click a polygon to select. Edit labels or delete incorrect detections, then continue.
      </p>
    </div>
  );
}
