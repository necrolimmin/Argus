import { load, save } from "../lib/storage";
import type {
  BulkResult,
  Camera,
  CameraSettings,
  Connection,
  CredentialProfile,
  Device,
  DeviceCreate,
  DeviceUpdate,
  ChannelInput,
  Found,
  ImportRow,
  ProbeResult,
  Employee,
  EmployeeInput,
  EventKind,
  FaceEvent,
  OrgUnit,
  Quality,
  Role,
  User,
} from "./types";

const TOKEN_KEY = "argus.token";

let token: string | null = load<string | null>(TOKEN_KEY, null);
let onUnauthorized: () => void = () => {};

export function getToken() {
  return token;
}

export function setToken(value: string | null) {
  token = value;
  save(TOKEN_KEY, value);
}

export function handleUnauthorized(cb: () => void) {
  onUnauthorized = cb;
}

/** Error carrying the backend's machine-readable code, e.g. "unit_has_cameras". */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError(0, "network");
  }

  if (res.status === 401 && token) {
    setToken(null);
    onUnauthorized();
  }
  if (!res.ok) {
    let code = `http_${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") code = body.detail;
      else if (Array.isArray(body.detail)) code = validationCode(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, code);
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("Content-Type") ?? "";
  return (type.includes("json") ? res.json() : res.text()) as Promise<T>;
}

// Pydantic validation errors: pick the custom code from a model validator
// ("Value error, rtsp_main_required") or fall back to a generic one.
function validationCode(detail: { msg?: string }[]): string {
  for (const d of detail) {
    const m = /Value error, ([a-z_]+)/.exec(d.msg ?? "");
    if (m) return m[1];
  }
  return "validation";
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
});

function query(params: Record<string, unknown>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((item) => q.append(k, String(item)));
    else q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string; user: User }>("/api/auth/login", json("POST", { username, password })),
  me: () => request<User>("/api/auth/me"),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("/api/auth/password", json("POST", { current_password, new_password })),

  users: () => request<User[]>("/api/users"),
  createUser: (body: { username: string; full_name: string; password: string; role: Role; org_unit_id: string | null }) =>
    request<User>("/api/users", json("POST", body)),
  updateUser: (id: string, body: Partial<{ full_name: string; password: string; role: Role; org_unit_id: string | null; is_active: boolean }>) =>
    request<User>(`/api/users/${id}`, json("PATCH", body)),
  deleteUser: (id: string) => request<void>(`/api/users/${id}`, { method: "DELETE" }),

  units: () => request<OrgUnit[]>("/api/org-units"),
  createUnit: (name: string, parent_id: string | null) =>
    request<OrgUnit>("/api/org-units", json("POST", { name, parent_id })),
  renameUnit: (id: string, name: string) => request<OrgUnit>(`/api/org-units/${id}`, json("PATCH", { name })),
  deleteUnit: (id: string) => request<void>(`/api/org-units/${id}`, { method: "DELETE" }),

  cameras: (params: { org_unit_id?: string | null } = {}) =>
    request<Camera[]>(`/api/cameras${query(params)}`),
  updateCamera: (id: string, body: CameraSettings) => request<Camera>(`/api/cameras/${id}`, json("PUT", body)),
  deleteCamera: (id: string) => request<void>(`/api/cameras/${id}`, { method: "DELETE" }),
  webrtc: (id: string, quality: Quality, sdp: string) =>
    request<string>(`/api/cameras/${id}/webrtc?quality=${quality}`, {
      method: "POST",
      body: sdp,
      headers: { "Content-Type": "application/sdp" },
    }),

  devices: () => request<Device[]>("/api/devices"),
  probeDevice: (body: Connection) => request<ProbeResult>("/api/devices/probe", json("POST", body)),
  createDevice: (body: DeviceCreate) => request<Device>("/api/devices", json("POST", body)),
  updateDevice: (id: string, body: DeviceUpdate) => request<Device>(`/api/devices/${id}`, json("PUT", body)),
  deleteDevice: (id: string) => request<void>(`/api/devices/${id}`, { method: "DELETE" }),
  syncDevice: (id: string) => request<ProbeResult>(`/api/devices/${id}/sync`, { method: "POST" }),
  addChannels: (id: string, channels: ChannelInput[]) =>
    request<Device>(`/api/devices/${id}/cameras`, json("POST", { channels })),
  bulkCreate: (body: {
    targets: { vendor: string; host: string; rtsp_port?: number; http_port?: number; name?: string }[];
    org_unit_id: string;
    credential_id: string | null;
    username: string;
    password: string;
  }) => request<BulkResult[]>("/api/devices/bulk", json("POST", body)),
  importPreview: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ImportRow[]>("/api/devices/import/preview", { method: "POST", body: form });
  },
  importDevices: (rows: ImportRow[]) =>
    request<{ devices: number; cameras: number; skipped_rows: number[] }>("/api/devices/import", json("POST", { rows })),
  importTemplate: async () => {
    const res = await fetch("/api/devices/import/template", { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new ApiError(res.status, `http_${res.status}`);
    return res.blob();
  },

  credentials: () => request<CredentialProfile[]>("/api/credentials"),
  saveCredential: (id: string | null, body: { name: string; username: string; password: string }) =>
    request<CredentialProfile>(id ? `/api/credentials/${id}` : "/api/credentials", json(id ? "PUT" : "POST", body)),
  deleteCredential: (id: string) => request<void>(`/api/credentials/${id}`, { method: "DELETE" }),

  scanDiscover: () => request<Found[]>("/api/scan/discover", { method: "POST" }),
  scanRange: (ranges: string[]) => request<Found[]>("/api/scan/range", json("POST", { ranges })),

  employees: (params: { org_unit_id?: string | null; q?: string; active?: boolean; offset?: number; limit?: number }) =>
    request<{ items: Employee[]; total: number }>(`/api/employees${query(params)}`),
  createEmployee: (body: EmployeeInput) => request<Employee>("/api/employees", json("POST", body)),
  updateEmployee: (id: string, body: EmployeeInput) => request<Employee>(`/api/employees/${id}`, json("PUT", body)),
  deleteEmployee: (id: string) => request<void>(`/api/employees/${id}`, { method: "DELETE" }),
  uploadPhoto: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Employee>(`/api/employees/${id}/photos`, { method: "POST", body: form });
  },
  deletePhoto: (id: string, photoId: string) =>
    request<Employee>(`/api/employees/${id}/photos/${photoId}`, { method: "DELETE" }),

  events: (params: { camera_ids: string[]; kind: EventKind; since?: string; before?: string; limit?: number }) =>
    request<FaceEvent[]>(`/api/events${query(params)}`),
  employeeFromEvent: (eventId: string, body: EmployeeInput) =>
    request<Employee>(`/api/events/${eventId}/employee`, json("POST", body)),
};
