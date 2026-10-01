# How estimation works

## Area estimation
1. Each structure region is a normalized polygon in 0–1 image coordinates
   (from SegFormer CMP masks and/or Gemini / Konva edits).
2. Optional **Depth Anything V2** (HF or Replicate) refines facade width/height
   from image aspect + depth planarity (MassingPro-inspired; still advisory).
3. Polygon area (shoelace) × facade width × height × mild depth foreshortening → sq ft.
4. Defaults: facade ~30 ft wide × height from photo aspect (overridable by user refs).
5. Railings use horizontal span × assumed 3 ft height.
6. Contractors/architects/builders may override areas.

## Quantity calculation
1. Active design maps each region → material.  
2. Base quantity = estimated area (or area ÷ coverage for paint liters, etc.).  
3. Final quantity = base × (1 + wastage%).  
4. Builders/contractors may override final quantities.

## Cost calculation
```
material_cost = final_qty × material_rate
labor_cost    = final_qty × labor_rate
line_total    = material_cost + labor_cost
grand_total   = Σ line_total
```
Project-level rate overrides recalculate costs immediately.

## Disclaimer
All figures are **advisory**, not legally binding quotations.
