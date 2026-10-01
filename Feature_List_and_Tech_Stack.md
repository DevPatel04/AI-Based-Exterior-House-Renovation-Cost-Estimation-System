# AI-Based Exterior House Renovation & Cost Estimation System

## Feature List, User Roles & Third-Party Mapping

**Document version:** 1.0  
**Based on:** AI-Based Exterior House Renovation & Cost Estimation System – Problem Statement & Detailed Requirements  
**Stack decisions:**
- Database: **PostgreSQL**
- File storage: **Local disk**
- Vision / analysis: **Google Gemini** + optional **SegFormer CMP** (HF Inference)
- Redesign images: **Replicate ControlNet** (preferred) + optional **fal.ai ControlNet** + **Cloudflare Workers AI** + optional Gemini HQ
- Area scale: polygon × facade refs + optional **Depth Anything V2** (HF / Replicate)
- Backend: **FastAPI (Python)**
- Frontend: **Next.js + TypeScript + Tailwind**
- PDF reports: **ReportLab**
- Region editing UI: **Konva / Fabric.js**
- Optional quality helper: **OpenCV** (also used for ControlNet Canny maps)

---

## 1. System overview

Homeowners and related professionals need a digital platform that can:

1. Accept exterior images of a residential building  
2. Generate redesigned visual options using selected construction materials  
3. Estimate material quantities required  
4. Calculate a detailed and transparent renovation cost  

The system acts as a **pre-construction planning assistant** and must not require professional architectural drawings or specialized measuring equipment.

### Scope assumptions
- Residential, low-rise buildings only (independent house, bungalow, or small apartment)
- Exterior renovation only (no interior design)
- No structural engineering calculations
- Cost estimates are advisory, not legally binding

---

## 2. User roles

| Role | Who | Main goals |
|------|-----|------------|
| **Homeowner** | Individual / new house owner | Upload house, try designs, get cost, download report |
| **Contractor** | Execution partner | Review designs, adjust rates/quantities, use report in quotes |
| **Architect** | Design advisor | Review regions/materials, refine design options |
| **Builder** | Construction team | Check quantities, labor cost, material needs |
| **Real estate consultant** | Advisor / seller support | Create visual options + cost for clients |
| **Material supplier** | Catalog / pricing partner | Manage materials, textures, rates, availability |
| **Admin** | System operator | Users, roles, catalog, default rates, system settings |

> Primary users from the requirement document: Homeowners / new house owners.  
> Secondary users: Contractors, Architects, Builders, Real estate consultants, Material suppliers.  
> Admin is included so multi-user access, catalog, and rates can be managed properly.

---

## 3. Complete feature list (by module)

### A. Account, roles & access

| ID | Feature | Covers requirement | Third-party / tech |
|----|---------|-------------------|--------------------|
| A1 | Sign up / login / logout | Multi-user | Custom + PostgreSQL (or NextAuth later) |
| A2 | Role assignment (Homeowner, Contractor, Architect, Builder, Consultant, Supplier, Admin) | All target users | PostgreSQL |
| A3 | Role-based permissions (who can edit catalog, rates, projects) | Secondary users + admin | Custom RBAC |
| A4 | User profile (name, contact, company for professionals) | Secondary users | PostgreSQL |
| A5 | Concurrent multi-user sessions | NFR: multiple users | FastAPI + PostgreSQL |

---

### B. Project management

| ID | Feature | Covers requirement | Third-party / tech |
|----|---------|-------------------|--------------------|
| B1 | Create renovation project | Goal / workflow | PostgreSQL |
| B2 | Save project (images, regions, materials, costs) | NFR: saving | PostgreSQL + local files |
| B3 | Re-open and re-edit project | NFR: re-editing | Custom |
| B4 | List / search own projects | Usability | Custom |
| B5 | Share / assign project to Contractor / Architect / Consultant (view or collaborate) | Secondary users | Custom + roles |
| B6 | Project status (Draft, Designed, Estimated, Reported) | Workflow | Custom |
| B7 | Soft-delete / archive project | Multi-user hygiene | Custom |

---

### C. Media upload (FR 5.1)

| ID | Feature | Covers requirement | Third-party / tech |
|----|---------|-------------------|--------------------|
| C1 | Upload exterior house image(s) | Accept exterior images | Local storage |
| C2 | Store files locally; save path in DB | File storage choice | Local disk + PostgreSQL |
| C3 | Extract / select clear usable view | Extract usable views | Gemini vision + UI crop |
| C4 | Reject extremely low-quality input | Reject bad input | Gemini + OpenCV (blur/resolution) |
| C5 | Guide user if image not usable (messages + tips) | Guide user | Custom UX copy |
| C6 | Support multiple exterior angles (optional views) | Better planning | Local storage |
| C7 | Preview uploaded image before continue | Non-technical UX | Frontend |

---

### D. Exterior structure identification (FR 5.2)

| ID | Feature | Covers requirement | Third-party / tech |
|----|---------|-------------------|--------------------|
| D1 | Detect main walls | Structure identification | SegFormer CMP → Gemini → Konva |
| D2 | Detect windows | Structure identification | SegFormer / Gemini |
| D3 | Detect balconies | Structure identification | SegFormer / Gemini |
| D4 | Detect pillars/columns | Structure identification | SegFormer / Gemini |
| D5 | Detect parapet walls | Structure identification | SegFormer / Gemini |
| D6 | Detect gate areas | Structure identification | SegFormer / Gemini |
| D7 | Detect roof edges | Structure identification | SegFormer / Gemini |
| D8 | Create mapped surface representation (regions overlay) | Mapped representation | Custom + Konva / Fabric.js |
| D9 | User reviews detected regions | Review regions | Frontend |
| D10 | User adjusts / corrects regions (draw, resize, delete, relabel) | Adjust areas | Konva / Fabric.js |
| D11 | Save corrected region map to project | Persistence | PostgreSQL |

---

### E. Design & material selection (FR 5.3)

| ID | Feature | Covers requirement | Third-party / tech |
|----|---------|-------------------|--------------------|
| E1 | Material catalog browsing | Material catalog | PostgreSQL |
| E2 | Catalog types: Paint, Stone cladding, Tiles, Texture finish, Glass railing, Metal railing, Panels | Material examples in FR | Seed data in DB |
| E3 | Material details (name, type, texture image, unit, coverage, default rate, durability/maintenance notes) | Material selection confusion | PostgreSQL + local texture files |
| E4 | Apply different materials to different house sections | Apply per part | Custom |
| E5 | Preview multiple material combinations | Preview combinations | Custom + image generation |
| E6 | Switch between saved designs | Switch designs | PostgreSQL design variants |
| E7 | Suitability hints (what suits walls vs railings, etc.) | Material selection confusion | Rules + optional Gemini text |
| E8 | Supplier role: add/edit/deactivate materials & textures | Material supplier user | Supplier / Admin UI |
| E9 | Admin: approve catalog changes | Catalog control | Admin role |

---

### F. Renovation visualization (FR 5.4)

| ID | Feature | Covers requirement | Third-party / tech |
|----|---------|-------------------|--------------------|
| F1 | Generate redesigned visual of user’s actual house | Redesigned output | Cloudflare Workers AI |
| F2 | Preserve original building structure | Preserve structure | Prompt + img2img / inpaint strength |
| F3 | Apply textures / colors / materials realistically | Realistic apply | Cloudflare (FLUX / SDXL img2img / inpaint) |
| F4 | Optional HQ redesign mode | Better output option | Gemini image API (optional paid) |
| F5 | Side-by-side / slider: original vs redesigned | Comparison | Frontend |
| F6 | Regenerate with same or new materials | Multiple options | Cloudflare / Gemini |
| F7 | Save redesign image locally + link in project | Persistence | Local disk + PostgreSQL |

---

### G. Surface area estimation (FR 5.5)

| ID | Feature | Covers requirement | Third-party / tech |
|----|---------|-------------------|--------------------|
| G1 | Estimate wall surface area | Area estimation | Custom geometry engine |
| G2 | Estimate balcony surfaces | Area estimation | Custom |
| G3 | Estimate pillar surfaces | Area estimation | Custom |
| G4 | Estimate railing length/area | Area estimation | Custom |
| G5 | Estimate cladding area | Area estimation | Custom |
| G6 | Use reference assumptions (standard door/window size) | Reference assumptions | Config defaults in DB |
| G7 | Perspective / pixel-to-real scale estimation | Perspective estimation | Depth Anything V2 + facade refs |
| G8 | Optional user input measurements (height, width, known reference) | User measurements | UI + DB |
| G9 | Show confidence / “approximate” disclaimer | Advisory estimates | UX copy |
| G10 | Contractor / Architect can override areas | Secondary users | Role permissions |

---

### H. Material quantity calculation (FR 5.6)

| ID | Feature | Covers requirement | Third-party / tech |
|----|---------|-------------------|--------------------|
| H1 | Compute required material quantity from areas | Quantity calculation | Custom rules engine |
| H2 | Apply approximate wastage % | Wastage | DB wastage rules |
| H3 | Apply coverage rules (e.g. paint sq ft per liter) | Coverage | Material master data |
| H4 | Output: paint area (sq ft), tiles count, stone cladding qty, railing length | Example outputs in FR | Custom |
| H5 | Builder / Contractor can adjust quantities | Secondary users | Role permissions |
| H6 | Recalculate when areas or materials change | Workflow | Custom |

---

### I. Cost estimation (FR 5.7)

| ID | Feature | Covers requirement | Third-party / tech |
|----|---------|-------------------|--------------------|
| I1 | Material cost from predefined rates | Material cost | PostgreSQL rate tables |
| I2 | Labor cost | Labor cost | Rate tables |
| I3 | Cost per category (paint, cladding, railing, etc.) | Per category | Custom |
| I4 | Grand total | Grand total | Custom |
| I5 | User modifies material rates | Modify rates | UI + recalculation |
| I6 | User modifies labor rates | Cost transparency | UI + recalculation |
| I7 | Auto-recalculate after rate / quantity change | Recalculated costs | Custom |
| I8 | Transparent line-item breakdown | Cost uncertainty problem | Report + UI |
| I9 | Admin / Supplier maintain default market rates | Supplier / Admin | Role features |
| I10 | Disclaimer: advisory, not legally binding | Assumptions | UX / report footer |

---

### J. Report generation (FR 5.8)

| ID | Feature | Covers requirement | Third-party / tech |
|----|---------|-------------------|--------------------|
| J1 | Downloadable report | Report generation | ReportLab |
| J2 | Include original image | Report content | Local files → PDF |
| J3 | Include redesigned image | Report content | Local files → PDF |
| J4 | Include selected materials | Report content | DB → PDF |
| J5 | Include quantity calculations | Report content | DB → PDF |
| J6 | Include cost breakdown | Report content | DB → PDF |
| J7 | Usable as discussion document with contractors | Goal of report | PDF layout |
| J8 | Optional role-based report branding (consultant / contractor logo) | Secondary users | Optional profile assets |

---

### K. Non-functional features (Section 6)

| ID | Feature | Covers requirement | Third-party / tech |
|----|---------|-------------------|--------------------|
| K1 | Simple guided wizard UI for non-technical users | Usable by non-technical users | Next.js UX |
| K2 | Works on standard internet (async jobs, progress UI) | Standard connections | FastAPI background tasks |
| K3 | Reasonable response time + loading states for AI | Reasonable time | Cloudflare + Gemini timeouts / retries |
| K4 | Save & resume anytime | Re-editing / saving | PostgreSQL |
| K5 | Handle multiple users simultaneously | Multi-user | Stateless API + DB |
| K6 | Exterior-only scope enforcement (no interior flows) | Assumptions | Product scope |
| K7 | No need for CAD / professional drawings | Constraints | Image-first flow |
| K8 | No specialized measuring hardware required | Constraints | Photo + optional manual measures |

---

### L. Documentation & system deliverables (Section 9)

| ID | Feature / deliverable | Covers requirement | Third-party / tech |
|----|----------------------|-------------------|--------------------|
| L1 | System architecture document | Deliverable 1 | Docs |
| L2 | User workflow document (per role) | Deliverable 2 | Docs |
| L3 | Working prototype (all core flows) | Deliverable 3 | Full stack |
| L4 | Estimation method documentation | Deliverable 4 | Docs |
| L5 | Limitations documentation | Deliverable 4 | Docs |

---

## 4. Role × feature matrix

| Feature area | Homeowner | Contractor | Architect | Builder | Consultant | Supplier | Admin |
|--------------|-----------|------------|-----------|---------|------------|----------|-------|
| Upload house & create project | Yes | Yes | Yes | View/edit assigned | Yes (for client) | No | Yes |
| Review / correct regions | Yes | Yes | Yes | Yes | Yes | No | Yes |
| Select materials / designs | Yes | Yes | Yes | Limited | Yes | No | Yes |
| Generate redesign visuals | Yes | Yes | Yes | View | Yes | No | Yes |
| Edit areas / quantities | Limited | Yes | Yes | Yes | Limited | No | Yes |
| Edit cost rates | Limited | Yes | Limited | Yes | Limited | Rates only | Yes |
| Manage material catalog | No | No | No | No | No | Yes | Yes |
| Download report | Yes | Yes | Yes | Yes | Yes | No | Yes |
| Manage users & roles | No | No | No | No | No | No | Yes |
| System settings / default rates | No | No | No | No | No | Partial | Yes |

---

## 5. Third-party & technology checklist

| Third-party / technology | Used for | Cost posture |
|--------------------------|----------|--------------|
| **PostgreSQL** | Users, roles, projects, regions, materials, rates, quantities, costs, file paths | Free (self-host / local) |
| **Google Gemini** | Image quality check, structure understanding, optional guidance text | Free vision / text tier |
| **Cloudflare Workers AI** | Renovation visualization (redesign image via FLUX / SDXL img2img / inpaint) | Free daily Neurons quota |
| **Gemini image API** *(optional)* | Higher-quality redesign mode | Paid per image |
| **OpenCV** | Extra low-quality image checks (blur / resolution) | Free / open source |
| **Konva / Fabric.js** | Draw / edit structure regions on photo | Free / open source |
| **ReportLab** | Downloadable PDF report | Free / open source |
| **Next.js + React + Tailwind** | Frontend application | Free / open source |
| **FastAPI** | Backend APIs and background jobs | Free / open source |
| **Local file storage** | Original images, redesigns, material textures | Free (local disk) |

### Explicitly not used in base plan
- AWS S3 / paid cloud object storage  
- Replicate / Fal as primary image API  
- Professional CAD / BIM tools  

---

## 6. Recommended system flow

```
User login (role-based)
    → Create / open project
    → Upload exterior image(s) → save locally
    → Quality check (Gemini + OpenCV)
    → Structure detection (SegFormer CMP → Gemini) → user review / correct regions
    → Select materials per region (catalog from PostgreSQL)
    → Generate redesign (Replicate ControlNet → fal → Cloudflare; optional Gemini HQ)
    → Compare original vs redesigned
    → Estimate areas (Depth Anything + polygon) → quantities → costs (editable rates)
    → Save project
    → Download PDF report (ReportLab)
```

---

## 7. Requirements coverage check

| Requirement section | Covered by feature IDs |
|---------------------|------------------------|
| 5.1 Media upload | C1–C7 |
| 5.2 Structure identification | D1–D11 |
| 5.3 Design & materials | E1–E9 |
| 5.4 Visualization | F1–F7 |
| 5.5 Area estimation | G1–G10 |
| 5.6 Quantity calculation | H1–H6 |
| 5.7 Cost estimation | I1–I10 |
| 5.8 Report generation | J1–J8 |
| 6 Non-functional requirements | K1–K8 |
| 4 Target users / roles | Section 2 + Section 4 + A1–A5 |
| 7–8 Assumptions & constraints | K6–K8, I10 |
| 9 Expected deliverables | L1–L5 |

---

## 8. What is built in-house (not third-party)

- Material catalog content and pricing / labor rates  
- Area, wastage, and coverage calculation formulas  
- Cost breakdown math and recalculation logic  
- Project workflow, statuses, and collaboration rules  
- Role-based access control rules  
- Local file path management  
- PDF report layout and content assembly  
- UI wizard and before / after comparison experience  

---

## 9. Summary

This document defines the **complete feature backlog** for the AI-Based Exterior House Renovation & Cost Estimation System, including:

- All functional requirements (5.1–5.8)  
- All non-functional requirements  
- All primary and secondary user roles (plus Admin)  
- Full third-party mapping aligned to the chosen free-first stack  
- Coverage mapping back to the original requirement document  

No requirement section from the source document is skipped.
