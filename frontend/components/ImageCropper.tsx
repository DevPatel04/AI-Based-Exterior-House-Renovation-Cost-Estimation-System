"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icons";

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
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [src, setSrc] = useState("");
  const [box, setBox] = useState({ x: 10, y: 10, w: 80, h: 70 }); // % of displayed image
  const drag = useRef<{ kind: string; sx: number; sy: number; start: typeof box } | null>(null);

  useEffect(() => {
    const url = URL.createObjectURL(file);
    setSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function onPointerDown(e: React.PointerEvent, kind: string) {
    // Measure against the image wrapper (same frame as onPointerMove) for both move and resize.
    const rect = (wrapRef.current ?? (e.currentTarget.parentElement as HTMLElement)).getBoundingClientRect();
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
    <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:p-5">
      <div>
        <h3 className="flex items-center gap-2 font-semibold text-slate-900">
          <Icon name="crop" className="h-4 w-4 text-brand-600" /> Frame the facade
        </h3>
        <p className="mt-0.5 text-sm text-slate-500">
          Drag the box to frame the house and use the corner handle to resize. Quality checks run on the cropped view.
        </p>
      </div>
      <div className="flex justify-center rounded-lg bg-slate-900/90 p-2">
        <div
          ref={wrapRef}
          className="relative inline-block max-w-full touch-none select-none overflow-hidden rounded"
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img ref={imgRef} src={src} alt="Photo to crop" className="block max-h-[60vh] max-w-full rounded" draggable={false} />
          <div
            className="absolute cursor-move border-2 border-white shadow-[0_0_0_9999px_rgba(15,23,42,0.55)]"
            style={{ left: `${box.x}%`, top: `${box.y}%`, width: `${box.w}%`, height: `${box.h}%` }}
            onPointerDown={(e) => onPointerDown(e, "move")}
          >
            <div className="pointer-events-none absolute inset-0 grid grid-cols-3 grid-rows-3">
              {Array.from({ length: 9 }).map((_, i) => (
                <div key={i} className="border border-white/25" />
              ))}
            </div>
            <div
              role="presentation"
              className="absolute bottom-0 right-0 h-6 w-6 cursor-se-resize rounded-tl-md border-l-2 border-t-2 border-white bg-accent-500"
              onPointerDown={(e) => {
                e.stopPropagation();
                onPointerDown(e, "resize");
              }}
            />
          </div>
        </div>
      </div>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <button type="button" className="btn-outline" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="btn-primary" onClick={applyCrop}>
          <Icon name="check" /> Apply crop & upload
        </button>
      </div>
    </div>
  );
}
