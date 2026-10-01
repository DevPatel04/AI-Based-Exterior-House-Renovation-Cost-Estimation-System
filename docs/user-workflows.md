# User workflows

The product is a guided wizard. A non-technical homeowner can finish a plan without drawings or a tape measure. Professionals join the same project to correct regions, quantities, and rates. Every figure in the UI and PDF is an advisory planning estimate.

## Shared wizard

After login, the user creates or opens a project. The workspace is six steps. The app advances the main action the first time a step is opened (detect, visualize, calculate, report) when the previous step has the data that action needs.

| Step | What the user does | What the system does |
|------|--------------------|----------------------|
| 1. Upload | Add one or more exterior photos. Crop if needed. Pick the primary view. | Stores the file, records size, shows quality tips. Does not block a soft or dark photo. |
| 2. Regions | Run detection. Drag, relabel, add, or delete polygons until the map matches the house. | Gemini (then optional fallbacks) proposes regions. Manual edits are kept on the next detect. |
| 3. Materials | Accept AI suggestions or pick a catalog finish per region. Save. Optionally add another design variant. | Writes the region → material map on the active design. |
| 4. Visualize | Generate the redesign. Compare original and result. Optionally regenerate in high-quality mode or switch designs. | Image model edits the primary photo using the saved materials. Status becomes `designed`. |
| 5. Estimate | Optionally enter facade width and height. Calculate. Adjust area, quantity, or rates if the role allows. | Estimates areas, purchase quantities, and material plus labor cost. Status becomes `estimated`. |
| 6. Report | Download the PDF. | Builds a discussion document with images, materials, quantities, costs, and a disclaimer. Status becomes `reported`. |

Projects can be reopened. Changing regions, materials, or rates and running the later steps again replaces the automatic estimate. User overrides are kept until the user changes them.

## Homeowner

Primary user. Goal: see a possible exterior and a planning budget before talking to a contractor.

1. Register or log in as homeowner.
2. Create a project and upload a daytime photo of the full facade.
3. Read the quality note. Upload a clearer photo if the tips say the shot is small, blurry, or dark.
4. Review detected walls, windows, doors, and other parts. Correct anything that is wrong. This step matters: later areas follow these polygons.
5. Use **Suggest materials** or choose finishes. Save.
6. Generate the redesign and compare it with the original.
7. Enter facade width and height if known. Otherwise leave them blank and let the photo estimate run. Review the line items.
8. Download the PDF to discuss with a contractor. The PDF states that the numbers are not a quotation.

A homeowner can edit material and labor rates on their own project. They cannot override measured areas or purchase quantities; those overrides are limited to contractor, architect, builder, and admin roles.

## Contractor

1. Register as contractor, or accept a share invite on a homeowner’s project.
2. Open the project. Correct regions if the detection missed an opening or included a sign or shadow.
3. Adjust quantities and rates to match a real quote.
4. Review the redesign with the client.
5. Download the report as a discussion draft, then replace rates with current supplier prices before issuing a formal quotation.

## Architect

1. Open an owned or shared project.
2. Refine region boundaries and material choices. Create a second design variant to compare finishes.
3. Generate a redesign for each variant.
4. Override areas when a site dimension is known.
5. Download the report for a design review. Architects do not edit rates unless they also hold a role that has `rates:edit`.

## Builder

1. Open a shared project (builders do not create projects).
2. Check region areas and the quantity schedule.
3. Override areas and final quantities, and edit labor or material rates.
4. Download the report for procurement planning.

Builders can edit the project and regions. They cannot assign materials or generate a redesign (`materials:select` and `visualize:generate` are not granted).

## Real estate consultant

1. Create a project for a listing or client.
2. Run the same upload → regions → materials → visualize → estimate → report path as a homeowner.
3. Share the project with the client’s contractor if needed.
4. Use the PDF as a visual and budget conversation piece. Consultants cannot override areas or quantities.

## Material supplier

1. Log in and open Catalog.
2. Add or edit materials: name, type, unit, coverage per unit, wastage percent, material rate, labor rate, suitable regions, and an optional texture image.
3. New rows wait for admin approval when the catalog requires it. Only active, approved materials appear in suggestions and in the project picker.

Suppliers do not upload houses or run estimates.

## Admin

1. Log in with the seeded admin account (`ADMIN_EMAIL` / `ADMIN_PASSWORD`).
2. Assign roles.
3. Approve supplier materials and maintain default rates.
4. Open any project, correct data, and download reports.

## Sharing

The owner invites another user by email and chooses editor or viewer. An editor with the right role can change regions, materials, and estimates. A viewer can open the project and download the report when their role includes `report:download`. Sharing never grants catalog approval or user administration.

## What “done” looks like

A finished walkthrough has:

- a primary exterior photo stored on the project
- a reviewed region map
- at least one saved design with materials on those regions
- a redesign image of that photo
- area lines, quantity lines, and a cost total
- a PDF the user can hand to a contractor, with the advisory disclaimer intact
