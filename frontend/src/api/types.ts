export type Role = "admin" | "operator";
export type OrgLevel = "company" | "branch" | "enterprise" | "section";
export type Vendor =
  | "hikvision"
  | "dahua"
  | "uniview"
  | "axis"
  | "vigi"
  | "reolink"
  | "ezviz"
  | "dvrip"
  | "onvif"
  | "rtsp"
  | "http"
  | "other";
export type DeviceKind = "camera" | "recorder";
export type Direction = "entry" | "exit" | "none";
export type Quality = "main" | "sub";
export type EventKind = "recognized" | "unknown";

export const LEVELS: OrgLevel[] = ["company", "branch", "enterprise", "section"];

export interface User {
  id: string;
  username: string;
  full_name: string;
  role: Role;
  org_unit_id: string | null;
  is_active: boolean;
}

export interface OrgUnit {
  id: string;
  parent_id: string | null;
  level: OrgLevel;
  name: string;
  camera_count: number;
  employee_count: number;
}

export interface ScheduleWindow {
  days: number[];
  start: string;
  end: string;
}

export interface Camera {
  id: string;
  device_id: string;
  name: string;
  channel: number;
  rtsp_main: string;
  rtsp_sub: string;
  org_unit_id: string;
  face_recognition: boolean;
  direction: Direction;
  schedule: ScheduleWindow[];
  recognition_stream: Quality;
  enabled: boolean;
  missing: boolean;
}

export type CameraSettings = Omit<Camera, "id" | "device_id" | "channel" | "missing">;

export interface Device {
  id: string;
  name: string;
  kind: DeviceKind;
  vendor: Vendor;
  host: string;
  rtsp_port: number;
  http_port: number;
  credential_id: string | null;
  username: string;
  has_password: boolean;
  org_unit_id: string;
  model: string;
  serial: string;
  mac: string;
  firmware: string;
  online: boolean | null;
  last_seen_at: string | null;
  cameras: Camera[];
}

export interface Connection {
  vendor: Vendor;
  host: string;
  rtsp_port: number;
  http_port: number;
  credential_id: string | null;
  username: string;
  password: string;
  rtsp_main: string;
  rtsp_sub: string;
  channel_count: number | null;
}

export interface ProbeChannel {
  channel: number;
  name: string;
  rtsp_main: string;
  rtsp_sub: string;
  ip: string;
  camera_id: string | null;
  duplicate_of: string;
}

export interface ProbeResult {
  ok: boolean;
  error: string;
  kind: DeviceKind;
  name: string;
  model: string;
  serial: string;
  mac: string;
  firmware: string;
  codec: string;
  rtsp_port: number | null;
  channels: ProbeChannel[];
  snapshot: string | null;
  warnings: string[];
  duplicates: { device_id: string; name: string; reason: string }[];
}

export interface ChannelInput {
  channel: number;
  name: string;
  org_unit_id: string | null;
  rtsp_main: string;
  rtsp_sub: string;
}

export interface DeviceCreate extends Connection {
  name: string;
  kind: DeviceKind;
  org_unit_id: string;
  model: string;
  serial: string;
  mac: string;
  firmware: string;
  channels: ChannelInput[];
}

export interface DeviceUpdate {
  name: string;
  org_unit_id: string;
  host: string;
  rtsp_port: number;
  http_port: number;
  credential_id: string | null;
  username: string;
  password: string;
}

export interface CredentialProfile {
  id: string;
  name: string;
  username: string;
  device_count: number;
}

export interface Found {
  ip: string;
  vendor: string;
  model: string;
  name: string;
  mac: string;
  serial: string;
  activated: boolean | null;
  http_port: number | null;
  rtsp_port: number | null;
  open_ports: number[];
  sources: string[];
  device_id: string | null;
  device_name: string;
}

export interface BulkResult {
  host: string;
  ok: boolean;
  error: string;
  device_id: string | null;
  cameras: number;
}

export interface ImportRow {
  row: number;
  name: string;
  vendor: string;
  host: string;
  port: number | null;
  username: string;
  password: string;
  channel: number;
  org_path: string;
  org_unit_id: string | null;
  face_recognition: boolean;
  direction: Direction;
  errors: string[];
}

export interface Photo {
  id: string;
  url: string;
}

export interface Employee {
  id: string;
  full_name: string;
  personnel_number: string | null;
  position: string;
  phone: string;
  org_unit_id: string;
  is_active: boolean;
  photos: Photo[];
}

export type EmployeeInput = Omit<Employee, "id" | "photos">;

export interface FaceEvent {
  id: string;
  kind: EventKind;
  camera_id: string | null;
  camera_name: string;
  direction: Direction;
  occurred_at: string;
  similarity: number | null;
  image_url: string;
  face_url: string;
  employee: { id: string; full_name: string; position: string; org_unit: string } | null;
  linked_employee_name: string;
}
