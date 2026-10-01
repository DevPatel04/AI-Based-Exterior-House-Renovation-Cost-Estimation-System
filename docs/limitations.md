# System limitations

The prototype plans an exterior refresh from a single photo and a price catalog. It does not measure the building, specify structure, or issue a quote. Read this next to [estimation-method.md](./estimation-method.md).

## Scope

- Low-rise residential exteriors only: an independent house, bungalow, or small apartment block seen from outside.
- No interiors, sites, roofs you cannot see, or boundary walls outside the frame.
- No structural design, load checks, waterproofing design, or code compliance.
- No CAD, BIM, or survey import. The region map is polygons on a photograph.
- One primary photo drives detection, redesign, and measurement. Extra uploads are references until the user marks one as primary. A single view hides side walls and anything occluded by trees, cars, or projections.

## Area and quantity accuracy

- Areas from a photo are approximate. Perspective, lens distortion, occlusion, and regions that are not on one flat plane all add error. A bay window, a deep balcony, or a wall at an angle will not match a tape measure.
- The AI size prior (door about 7 ft, storey about 10–12 ft, facade roughly 8–120 ft wide and 8–80 ft tall) is a residential assumption. Unusual proportions are rejected or scaled poorly.
- The polygon fallback treats normalized image area as a fraction of a flat facade rectangle. That is not a perspective solve. Depth Anything, when used, only nudges scale and foreshortening.
- Default facade size is 30 × 22 ft when neither the user nor a model supplies a size. Totals on that path are illustrations until someone enters real dimensions.
- Railings on the formula path use a fixed 3 ft height times horizontal span. Real railing height and returns are not measured.
- Windows and gates under about 1 sq ft are discarded as noise. A real small opening can disappear with them. Signs and shadows can still be labeled as openings; the user is expected to delete those regions before estimating.
- Detection can miss openings or merge two windows into one box. Quantities follow the corrected map. If the map is wrong, the estimate is wrong.
- AI quantities may round for purchase and may not match `area / coverage` exactly. The formula path ignores offcuts beyond the single wastage percent and does not add primer, adhesive, or fixings as separate materials unless they are their own catalog rows.
- User quantity overrides freeze that line. A later rate edit recalculates with formulas for every non-overridden material and does not re-run the AI quantity pass.

## Cost

- Catalog rates, including the seed data, are placeholders. They are not a city, date, or supplier price list. Labor is a rate per purchase unit, not a measured crew-day.
- No tax, transport, scaffolding, waste disposal, or contractor margin unless someone folds those into the rate by hand.
- Overrides apply only to the current project. They do not update the catalog.
- The grand total is the sum of material and labor lines for materials assigned on the active design. Regions with no material are omitted from cost.

## Images and redesign

- Quality checks advise only. A dark, blurry, or interior photo can still be uploaded and will produce weak detection and a weak estimate.
- Redesign is a generative edit. It can change windows, proportions, or background even when the prompt asks to keep the structure. It is a preview, not a construction drawing, and it has no pixel-accurate material takeoff.
- High-quality mode still depends on the configured Gemini image models and on paid API access. Failure returns an error. The app does not substitute a local color wash (`ALLOW_LOCAL_REDESIGN_FALLBACK` is off).
- Cloudflare redesign is off unless explicitly enabled, and provider limits (size, quota) can reject a request.
- Material texture files influence the prompt. They are not composited as a measured cladding layout.

## Detection dependencies

- Best structure detection needs `GEMINI_API_KEY`. SegFormer needs a Hugging Face token. Grounded-SAM needs a Replicate token. If those are absent, OpenCV is the last resort and will miss or mislabel parts.
- OpenCV enrichment after a good Gemini result is intentionally limited, because it adds false windows. Sparse Gemini results may still be noisy after enrichment.
- Re-running detect deletes automatic regions and keeps manual ones. Material assignments that pointed at deleted region ids must be chosen again.

## Access and operations

- Permissions are role-based. A homeowner cannot override areas or quantities. A builder cannot generate a redesign. A supplier only manages the catalog.
- Files live on the API machine’s disk. They are not in PostgreSQL. A deploy without a persistent upload volume loses photos, redesigns, and PDFs even though the database rows remain.
- AI calls are synchronous from the user’s point of view. Slow or rate-limited providers surface as a failed step, not a background job the user can leave and resume.
- The PDF is a discussion document. The disclaimer in the report is part of the product: figures are not a quotation, contract, or legally binding offer. A licensed contractor still has to measure the site and price the work.
