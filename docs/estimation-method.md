# How estimation works

Estimation turns the reviewed region map and the active design’s materials into three numbers: surface area, purchase quantity, and cost. It runs in two API calls from the Estimate step.

1. `POST /api/projects/{id}/estimation/areas` — facade size and area per region.
2. `POST /api/projects/{id}/estimation/calculate` — quantities and costs for the active design.

Results are stored on the project (`AreaEstimate`, `QuantityLine`, `CostLine`). The PDF reads those rows. Nothing here is a measured survey.

Currency is Indian rupees. Rates come from the material catalog unless the user overrides them on the project.

## Inputs

| Input | Source |
|-------|--------|
| Region polygons | Detection plus any user edits. Coordinates are normalized, 0–1, on the primary photo. |
| Region type | `main_wall`, `window`, `balcony`, `pillar`, `parapet`, `gate`, `roof_edge`, `railing`, `other` |
| Optional facade width and height (ft) | Typed on the Estimate step. When set, they replace the AI facade size. |
| Material per region | Saved on the active design |
| Coverage, unit, wastage %, material rate, labor rate | Material catalog |
| Rate overrides | Project-level, when a user with `rates:edit` changes a rate |

Regions the user has overridden are not replaced by the next automatic area pass. Quantity lines marked as user overrides are kept and are not sent back through the AI quantity model.

## Area estimation

### Preferred path: Gemini quantity survey

When the primary image exists, `estimate_facade_and_areas_ai` sends the photo and each region’s normalized box to Gemini. The prompt asks for:

- facade width and height in feet, using an exterior door of about 7 ft and a low-rise storey of about 10–12 ft when the user did not type a size
- `area_sq_ft` for every region
- `length_ft` for linear parts (gate, railing, roof edge)
- `include: false` for false detections such as signs, posters, or tiny noise windows

The response is accepted only if facade width is between 8 and 120 ft and height is between 8 and 80 ft, and at least one region comes back. User-entered width or height overwrites the AI facade size after that check. A region is dropped when `include` is false, when area is under 1 sq ft, or when area exceeds 1.5 times facade width times facade height.

Stored method: `gemini_vision_qs`. Confidence is the average of the region’s detection confidence and the model’s confidence, capped at 0.95.

### Fallback path: polygon scale

Used when Gemini is missing, errors, or returns an unusable size.

Facade size is chosen in this order:

1. **Depth Anything V2** (`ENABLE_DEPTH_SCALE` and `HF_TOKEN`), only when the user did not supply both width and height. The depth map also applies a mild foreshortening factor per region. Method: `polygon_norm_x_<depth method>`, plus `+depth_foreshorten` when the factor is not 1.
2. **User reference**, when both width and height were typed. Method: `user_reference`. Confidence 0.95. No depth map.
3. **Defaults**, 30 ft wide by 22 ft high, if nothing else is available. Method: `polygon_norm_x_reference_facade`. Confidence is the region’s detection confidence (typically around 0.5 before any depth blend).

Area for a region:

```
polygon area (shoelace, normalized) × facade width (ft) × facade height (ft) × depth factor
```

The shoelace result is a fraction of the image, so multiplying by facade width and height treats that fraction as a fraction of the facade rectangle. That assumes the polygon is on the facade plane. It is a planning approximation.

Linear regions on this path:

- Railing, roof edge, and gate also get `length_ft` = horizontal span of the polygon × facade width.
- Railing area is then replaced with `length_ft × 3` ft, a nominal railing height, instead of the raw polygon area.

Polygons that are tiny in the image are dropped before this math when they were not approved by the AI path: windows under 0.4% of the image, gates under 0.6%, main walls under 5%, anything else under 0.2%. After the math, window and gate areas under 1 sq ft are dropped.

### User area override

A user with `areas:override` (contractor, architect, builder, admin) can set area and optional length. Method becomes `user_override`, confidence 1. Later automatic runs skip that region.

## Quantity calculation

Quantities are grouped by material across every region on the active design. Two regions with the same paint become one purchase line.

### Formula baseline

For each region–material pair, start from that region’s area in square feet (user override wins over the automatic area).

```
if the material has coverage_per_unit and its unit is liter, litre, bag, piece, or panel:
    base += area / coverage_per_unit
else:
    base += area
```

Paint in liters is the usual coverage case. Materials sold by area (square foot) keep the area as the base quantity.

### Preferred path: Gemini quantities

When automatic quantities are requested, the same photo, the area summary, and the catalog rows (coverage, unit, default wastage, suitable regions) are sent to Gemini. The model returns, per material:

- `base_quantity`
- `wastage_percent` (clamped to 0–25; the prompt suggests about 5–15% for finishes and 3–8% for railings)
- unit

If that call fails, the formula baseline and the catalog wastage percent are used instead.

### Final quantity

```
final_quantity = base_quantity × (1 + wastage_percent / 100)
```

A user with `quantities:override` can set `final_quantity` directly. That line is kept. Recalculation after an override does not call the AI quantity model again, so other materials on the same project also stay on the formula path until the user runs a fresh calculate from the Estimate step.

## Cost calculation

For each material line:

```
material_rate = project override, if set, otherwise catalog material_rate
labor_rate    = project override, if set, otherwise catalog labor_rate

material_cost = final_quantity × material_rate
labor_cost    = final_quantity × labor_rate
line_total    = material_cost + labor_cost
```

```
material_total = Σ material_cost
labor_total    = Σ labor_cost
grand_total    = material_total + labor_total
```

Changing a rate saves a `RateOverride` and recalculates immediately, again without a new AI quantity pass. Costs are per material, which is also the catalog category (paint, stone cladding, and so on). There is no separate tax, scaffolding, or preliminaries line.

After a successful calculate, project status is `estimated`.

## What the user sees

The Estimate step lists areas, then quantity and cost lines, with material total, labor total, and grand total. The PDF repeats the quantity schedule and the cost breakdown and states that the document is an advisory planning estimate, not a quotation, contract, or legally binding offer.

## Worked sketch

A main wall of 400 sq ft is assigned a paint that covers 100 sq ft per liter, with 10% wastage, material rate ₹80 per liter, and labor rate ₹40 per liter.

Formula path:

```
base          = 400 / 100 = 4 liters
final         = 4 × 1.10 = 4.4 liters
material_cost = 4.4 × 80 = ₹352
labor_cost    = 4.4 × 40 = ₹176
line_total    = ₹528
```

On the AI quantity path the base and wastage can differ (the model may round to a purchasable amount). The cost formulas stay the same. If the user types a facade size or overrides the wall area before calculate, the 400 sq ft input changes and both paths scale from that new area.
