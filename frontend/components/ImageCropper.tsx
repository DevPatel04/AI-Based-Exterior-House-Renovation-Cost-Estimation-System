"use client";

import { useEffect, useRef, useState } from "react";

/** Simple crop UI: drag a box, export cropped File for upload (C3). */
export default function ImageCropper({
  file,
  onCancel,
  onCropped,
}: {
  file: File;
  onCancel: () => void;
  onCropped: (file: File) => void;
}) {
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [src, setSrc] = useState("");
  const [box, setBox] = useState({ x: 10, y: 10, w: 80, h: 70 }); // % of displayed image
  const drag = useRef<{ kind: string; sx: number; sy: number; start: typeof box } | null>(null);

  useEffect(() => {
    const url = URL.createObjectURL(file);
    setSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function onPointerDown(e: React.PointerEvent, kind: string) {
    const rect = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
    drag.current = {
      kind,
      sx: ((e.clientX - rect.left) / rect.width) * 100,
      sy: ((e.clientY - rect.top) / rect.height) * 100,
      start: { ...box },
    };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent) {
    if (!drag.current) return;
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;
    const dx = x - drag.current.sx;
    const dy = y - drag.current.sy;
    const s = drag.current.start;
    if (drag.current.kind === "move") {
      setBox({
        x: Math.min(100 - s.w, Math.max(0, s.x + dx)),
        y: Math.min(100 - s.h, Math.max(0, s.y + dy)),
        w: s.w,
        h: s.h,
      });
    } else {
      setBox({
        x: s.x,
        y: s.y,
        w: Math.min(100 - s.x, Math.max(10, s.w + dx)),
        h: Math.min(100 - s.y, Math.max(10, s.h + dy)),
      });
    }
  }

  function onPointerUp() {
    drag.current = null;
  }

  async function applyCrop() {
    const img = imgRef.current;
    if (!img) return;
    const canvas = document.createElement("canvas");
    const sx = (box.x / 100) * img.naturalWidth;
    const sy = (box.y / 100) * img.naturalHeight;
    const sw = (box.w / 100) * img.naturalWidth;
    const sh = (box.h / 100) * img.naturalHeight;
    canvas.width = Math.max(1, Math.round(sw));
    canvas.height = Math.max(1, Math.round(sh));
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
    if (!blob) return;
    onCropped(new File([blob], file.name.replace(/\.\w+$/, "") + "-crop.jpg", { type: "image/jpeg" }));
  }

  return (
    <div className="card-panel p-4 space-y-3">
      <h3 className="font-semibold">Crop usable view</h3>
      <p className="text-sm text-slate">Drag the box to frame the facade, then apply crop before quality check.</p>
      <div
        className="relative inline-block max-w-full select-none"
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img ref={imgRef} src={src} alt="crop source" className="max-h-80 rounded-lg block" />
        <div
          className="absolute border-2 border-pine bg-pine/20 cursor-move"
          style={{ left: `${box.x}%`, top: `${box.y}%`, width: `${box.w}%`, height: `${box.h}%` }}
          onPointerDown={(e) => onPointerDown(e, "move")}
        >
          <div
            className="absolute right-0 bottom-0 w-4 h-4 bg-clay cursor-se-resize"
            onPointerDown={(e) => {
              e.stopPropagation();
              onPointerDown(e, "resize");
            }}
          />
        </div>
      </div>
      <div className="flex gap-2">
        <button type="button" className="btn-primary" onClick={applyCrop}>
          Apply crop & continue
        </button>
        <button type="button" className="btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
