# How estimation works

## Area estimation
1. **Gemini vision (preferred)** looks at the facade photo + detected region boxes and returns:
   - Estimated facade width / height (ft) using door ~7 ft and storey priors
   - Per-region `area_sq_ft` / `length_ft`
   - `include: false` for false detections (signs, tiny noise windows)
2. Optional user **Facade width / height** overrides AI size when provided.
3. Fallback (no Gemini key): polygon shoelace × facade size (+ optional Depth Anything scale).
4. Tiny noise polygons are dropped (< ~1 sq ft openings).

## Quantity calculation
1. Active design maps each region → material.
2. **Gemini** estimates purchase quantities from areas + catalog coverage / wastage.
3. Fallback: `base = area` or `area ÷ coverage`; `final = base × (1 + wastage%)`.
4. Builders may override final quantities.

## Material suggestions
Gemini vision picks one catalog material per region from the photo (cohesive finishes).
Rule-based catalog match is used only if Gemini is unavailable.

## Cost calculation
```
material_cost = final_qty × material_rate
labor_cost    = final_qty × labor_rate
line_total    = material_cost + labor_cost
grand_total   = Σ line_total
```

## Disclaimer
All figures are **advisory**, not legally binding quotations.
Requires a valid `GEMINI_API_KEY` (AI Studio `AIza…` key) for AI path.
