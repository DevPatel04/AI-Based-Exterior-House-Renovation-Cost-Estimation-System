/**
 * Browser must never call Railway private hostnames (*.railway.internal).
 * - Local: http://localhost:8000
 * - Railway: leave NEXT_PUBLIC_API_URL empty and set BACKEND_URL for Next rewrites,
 *   OR set NEXT_PUBLIC_API_URL to the backend's public https://*.up.railway.app URL.
 */
function resolveApiUrl(): string {
  const raw = (process.env.NEXT_PUBLIC_API_URL || "").trim().replace(/\/$/, "");
  if (raw.includes(".railway.internal")) {
    return "";
  }
  if (raw) return raw;
  // Empty NEXT_PUBLIC → same-origin (Next.js rewrites proxy to BACKEND_URL)
  if (process.env.NODE_ENV === "production") return "";
  return "http://localhost:8000";
}

const API_URL = resolveApiUrl();

/** Downscale large phone photos before upload so the API responds faster. */
async function compressImageForUpload(file: File, maxEdge = 1600, quality = 0.85): Promise<File> {
  if (!file.type.startsWith("image/") || file.type === "image/gif") return file;
  if (file.size < 400_000) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
    if (scale >= 1 && file.size < 1_500_000) {
      bitmap.close();
      return file;
    }
    const w = Math.max(1, Math.round(bitmap.width * scale));
    const h = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      bitmap.close();
      return file;
    }
    ctx.drawImage(bitmap, 0, 0, w, h);
    bitmap.close();
    const blob: Blob | null = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", quality)
    );
    if (!blob || blob.size >= file.size) return file;
    const name = file.name.replace(/\.\w+$/, "") + ".jpg";
    return new File([blob], name, { type: "image/jpeg", lastModified: Date.now() });
  } catch {
    return file;
  }
}

export type RoleName =
  | "homeowner"
  | "contractor"
  | "architect"
  | "builder"
  | "consultant"
  | "supplier"
  | "admin";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

/** Notify AppShell that login/logout changed the token (layout does not remount). */
function emitAuthChange() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("facadeplan-auth"));
  }
}

export function setToken(token: string) {
  localStorage.setItem("token", token);
  emitAuthChange();
}

export function clearToken() {
  localStorage.removeItem("token");
  emitAuthChange();
}

/** Turn FastAPI error payloads (string or 422 validation list) into a readable sentence. */
function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d: any) => {
        if (!d || typeof d !== "object" || !d.msg) return null;
        const field = Array.isArray(d.loc) ? d.loc.filter((p: unknown) => p !== "body").join(".") : "";
        return field ? `${String(field).replace(/_/g, " ")}: ${d.msg}` : d.msg;
      })
      .filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  return JSON.stringify(detail);
}

async function request<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!(options.body instanceof FormData) && !headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      /* ignore */
    }
    throw new Error(formatDetail(detail));
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res as unknown as T;
}

export const api = {
  register: (body: object) =>
    request("/api/auth/register", { method: "POST", body: JSON.stringify(body) }),
  login: async (email: string, password: string) => {
    const form = new URLSearchParams();
    form.set("username", email);
    form.set("password", password);
    const res = await fetch(`${API_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form,
    });
    if (!res.ok) {
      let detail = "Login failed";
      try {
        const data = await res.json();
        detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data);
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
    return res.json() as Promise<{ access_token: string }>;
  },
  me: () => request<any>("/api/auth/me"),
  updateMe: (body: object) =>
    request("/api/auth/me", { method: "PATCH", body: JSON.stringify(body) }),
  changePassword: (body: { current_password: string; new_password: string }) =>
    request("/api/auth/me/password", { method: "POST", body: JSON.stringify(body) }),
  uploadLogo: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<any>("/api/auth/me/logo", { method: "POST", body: fd });
  },
  listUsers: () => request<any[]>("/api/auth/users"),
  assignRole: (userId: number, role: string) =>
    request(`/api/auth/users/${userId}/roles`, {
      method: "POST",
      body: JSON.stringify({ role }),
    }),
  listProjects: () => request<any[]>("/api/projects"),
  createProject: (body: object) =>
    request("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  getProject: (id: number) => request<any>(`/api/projects/${id}`),
  updateProject: (id: number, body: object) =>
    request(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  archiveProject: (id: number) => request(`/api/projects/${id}`, { method: "DELETE" }),
  shareProject: (id: number, body: object) =>
    request(`/api/projects/${id}/members`, { method: "POST", body: JSON.stringify(body) }),
  listMembers: (id: number) => request<any[]>(`/api/projects/${id}/members`),
  uploadImage: async (projectId: number, file: File, setPrimary = false) => {
    const fd = new FormData();
    const compressed = await compressImageForUpload(file);
    fd.append("file", compressed);
    fd.append("set_primary", setPrimary ? "true" : "false");
    return request<any>(`/api/projects/${projectId}/images`, { method: "POST", body: fd });
  },
  setPrimaryImage: (projectId: number, imageId: number) =>
    request(`/api/projects/${projectId}/images/${imageId}/set-primary`, { method: "POST" }),
  listImages: (projectId: number) => request<any[]>(`/api/projects/${projectId}/images`),
  imageUrl: (projectId: number, imageId: number) =>
    `${API_URL}/api/projects/${projectId}/images/${imageId}/file`,
  detectRegions: (projectId: number) =>
    request<any[]>(`/api/projects/${projectId}/regions/detect`, { method: "POST" }),
  listRegions: (projectId: number) => request<any[]>(`/api/projects/${projectId}/regions`),
  createRegion: (projectId: number, body: object) =>
    request(`/api/projects/${projectId}/regions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateRegion: (projectId: number, regionId: number, body: object) =>
    request(`/api/projects/${projectId}/regions/${regionId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteRegion: (projectId: number, regionId: number) =>
    request(`/api/projects/${projectId}/regions/${regionId}`, { method: "DELETE" }),
  listMaterials: (includeInactive = false) =>
    request<any[]>(`/api/materials${includeInactive ? "?include_inactive=true" : ""}`),
  createMaterial: (body: object) =>
    request("/api/materials", { method: "POST", body: JSON.stringify(body) }),
  updateMaterial: (id: number, body: object) =>
    request(`/api/materials/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  uploadTexture: (materialId: number, file: File, label?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (label) fd.append("label", label);
    return request(`/api/materials/${materialId}/textures`, { method: "POST", body: fd });
  },
  listTextures: (materialId: number) => request<any[]>(`/api/materials/${materialId}/textures`),
  listDesigns: (projectId: number) => request<any[]>(`/api/projects/${projectId}/designs`),
  createDesign: (projectId: number, name: string) =>
    request(`/api/projects/${projectId}/designs`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  activateDesign: (projectId: number, designId: number) =>
    request(`/api/projects/${projectId}/designs/${designId}/activate`, { method: "POST" }),
  assignMaterials: (projectId: number, designId: number, items: object[]) =>
    request(`/api/projects/${projectId}/designs/${designId}/materials`, {
      method: "POST",
      body: JSON.stringify(items),
    }),
  getDesignMaterials: (projectId: number, designId: number) =>
    request<any[]>(`/api/projects/${projectId}/designs/${designId}/materials`),
  visualize: (projectId: number, designId: number, hq_mode = false) =>
    request(`/api/projects/${projectId}/designs/visualize`, {
      method: "POST",
      body: JSON.stringify({ design_id: designId, hq_mode }),
    }),
  redesignUrl: (projectId: number, designId: number) =>
    `${API_URL}/api/projects/${projectId}/designs/${designId}/redesign`,
  estimateAreas: (projectId: number, body?: object) =>
    request(`/api/projects/${projectId}/estimation/areas`, {
      method: "POST",
      body: JSON.stringify(body || {}),
    }),
  listAreas: (projectId: number) => request<any[]>(`/api/projects/${projectId}/estimation/areas`),
  overrideArea: (projectId: number, body: object) =>
    request(`/api/projects/${projectId}/estimation/areas/override`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  calculate: (projectId: number) =>
    request(`/api/projects/${projectId}/estimation/calculate`, { method: "POST" }),
  listQuantities: (projectId: number) =>
    request<any[]>(`/api/projects/${projectId}/estimation/quantities`),
  overrideQuantity: (projectId: number, body: object) =>
    request(`/api/projects/${projectId}/estimation/quantities/override`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  setRates: (projectId: number, body: object) =>
    request(`/api/projects/${projectId}/estimation/rates`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getCosts: (projectId: number) => request<any>(`/api/projects/${projectId}/estimation/costs`),
  createReport: (projectId: number, designId?: number) =>
    request(
      `/api/projects/${projectId}/reports${designId ? `?design_id=${designId}` : ""}`,
      { method: "POST" }
    ),
  listReports: (projectId: number) => request<any[]>(`/api/projects/${projectId}/reports`),
  reportDownloadUrl: (projectId: number, reportId: number) =>
    `${API_URL}/api/projects/${projectId}/reports/${reportId}/download`,
};

/** Fetch a protected file with the bearer token and trigger a browser download. */
export async function downloadAuthed(url: string, filename: string) {
  const token = getToken();
  const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blobUrl = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
}

export { API_URL };
