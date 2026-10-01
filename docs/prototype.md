# Functioning prototype

This repository is a runnable prototype of the exterior renovation planner. The demonstration path is one project in the wizard: upload a photo, apply materials, generate a redesign, estimate area, and estimate cost. Setup commands are in the [root README](../README.md).

You need:

- PostgreSQL, migrated and seeded
- API on port 8000 and the Next.js app on port 3000
- `GEMINI_API_KEY` in `backend/.env` for detection, material suggestions, photoreal redesign, and AI area and quantity estimates

Without that key, upload and the manual wizard still work. Detection falls through to SegFormer, Grounded-SAM, or OpenCV if those are configured. Redesign returns an error instead of a fake image. Area estimation uses polygon math and optional depth, and quantities use catalog coverage and wastage.

Sample exterior photos, if present, are in `sample_images/`.

## 1. Image upload

1. Register or log in and create a project from the dashboard.
2. Open the project. Stay on **Upload**.
3. Choose a clear daytime photo of a house exterior. Crop to the facade if the frame includes a lot of sky, cars, or neighbors.
4. Confirm the upload. The thumbnail appears, with a short quality note (resolution, blur, or brightness). The note does not block the next step.
5. If you add a second angle, mark the best view as primary. Detection, redesign, and estimation all use the primary image.

What is stored: the file under `backend/uploads/originals/`, plus width, height, quality flag, and quality message on the project.

## 2. Material application

1. Open **Regions**. Detection runs on the primary photo and draws polygons for wall, windows, doors, and any other parts the model finds.
2. Correct the map. Delete false regions (signs, shadows, furniture). Resize boxes that spill into sky or ground. Add a missing balcony, parapet, or gate if you need it in the estimate.
3. Open **Materials**. Run **Suggest materials** or pick a catalog item per region (paint, stone, tiles, texture, glass or metal railing, panels).
4. Save. The assignment is stored on the active design. Add another design if you want a second finish scheme; each design keeps its own material map and, after visualize, its own redesign.

What is stored: `Design` plus `DesignRegionMaterial` rows. Only active, approved catalog materials can be saved.

## 3. Redesigned output

1. Open **Visualize**. Generation starts when a design has saved materials and does not yet have an image.
2. Wait for the image model to return. The screen shows the original and the redesign together.
3. If you want a stronger model pass, generate again with high-quality mode.
4. Change materials, save, and generate again to replace the image. Switch the active design to compare variants.

The redesign is an edit of the user’s photo, prompted with each region’s material. It is stored on the design and loaded through an authenticated download route. If Gemini image generation fails and Cloudflare redesign is off, the step shows an error and does not invent a flat color preview.

## 4. Area estimation

1. Open **Estimate**.
2. Optionally type facade width and height in feet. If you know one or both, the estimate uses your numbers for facade size. If you leave them blank, Gemini estimates size from the photo (door height about 7 ft, storey height about 10–12 ft) and assigns an area to each region.
3. Run calculate if it did not start on its own.
4. Read the area table: square feet per region, length for rails, gates, and roof edges when provided, and the method name (`gemini_vision_qs` when the AI path succeeded).

False detections that the quantity-survey pass marks as noise are omitted. Very small window or gate areas under about 1 sq ft are dropped. Professionals with area-override permission can type a measured area; that value is kept on the next calculate.

## 5. Cost estimation

The same **Estimate** step continues from areas into money:

1. Each region’s area is tied to the material saved on the active design.
2. Purchase quantity is estimated per material (AI, or coverage and wastage if AI is unavailable), then material cost and labor cost are `quantity × rate`.
3. The screen shows line items, material total, labor total, and grand total in INR.
4. Where the role allows, edit a material rate or labor rate. The totals recalculate. Contractors and builders can also override a quantity; that override is kept.

Rates start from the seeded catalog. They are not live market prices. Change them before treating the total as a budget you would share.

## 6. Leave with a report

Open **Report** and download the PDF. It includes the original, the redesign, materials by region, the quantity schedule, the cost breakdown, and a statement that the document is not a quotation.

## What a successful demo shows

| Capability | You should see |
|------------|----------------|
| Image upload | Primary photo on the project, with a quality note |
| Material application | A saved material on each region you care about |
| Redesigned output | A new image of the same house using those finishes |
| Area estimation | Square-foot (and some length) figures with a method label |
| Cost estimation | Quantity, material cost, labor cost, and a grand total |

If redesign or AI estimation fails, check the API log and `GEMINI_API_KEY`. The wizard does not silently substitute a non-AI redesign.
