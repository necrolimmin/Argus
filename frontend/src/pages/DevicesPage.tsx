import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronRight,
  FileSpreadsheet,
  KeyRound,
  Pencil,
  Plus,
  Radar,
  RefreshCw,
  ScanFace,
  Router,
  Search,
  Settings2,
  Trash2,
} from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import { api } from "../api/client";
import { keys, useDevices, useUnits } from "../api/queries";
import type { Camera, Device, Vendor } from "../api/types";
import { DirectionBadge } from "../components/DirectionBadge";
import { Confirm } from "../components/Modal";
import { type RowAction, RowActions } from "../components/RowActions";
import { EmptyState, ErrorState, Skeleton } from "../components/States";
import { intlLocale } from "../i18n";
import { errorText } from "../lib/errors";
import { isAdmin, useAuth, useUi } from "../lib/store";
import { buildTree, flatten, unitPath } from "../lib/tree";
import { CameraModal } from "./CameraModal";
import { AddDeviceModal } from "./devices/AddDeviceModal";
import { CredentialsModal } from "./devices/CredentialsModal";
import { DeviceModal } from "./devices/DeviceModal";
import { ImportModal } from "./devices/ImportModal";
import { ScanModal } from "./devices/ScanModal";
import { SyncModal } from "./devices/SyncModal";

type Status = "all" | "online" | "offline" | "unknown";
type Dialog =
  | { kind: "add"; preset?: { vendor: Vendor; host: string; http_port?: number | null } }
  | { kind: "scan" }
  | { kind: "import" }
  | { kind: "creds" }
  | { kind: "device"; device: Device }
  | { kind: "sync"; device: Device }
  | { kind: "camera"; camera: Camera }
  | { kind: "deleteDevice"; device: Device }
  | { kind: "deleteCamera"; camera: Camera };

function statusOf(d: Device): Exclude<Status, "all"> {
  return d.online === null ? "unknown" : d.online ? "online" : "offline";
}

export function DevicesPage() {
  const { t } = useTranslation();
  const admin = isAdmin(useAuth((s) => s.user));
  const notify = useUi((s) => s.notify);
  const qc = useQueryClient();
  const list = useDevices();
  const devices = list.data ?? [];
  // react-query keeps the last good data when a refresh fails.
  const hasData = list.data !== undefined;
  const { data: units = [] } = useUnits();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<Status>("all");
  const [vendor, setVendor] = useState("");
  const [unitId, setUnitId] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [dialog, setDialog] = useState<Dialog | null>(null);

  const unitOptions = useMemo(() => flatten(buildTree(units)), [units]);
  const unitNames = useMemo(() => new Map(units.map((u) => [u.id, u.name])), [units]);

  // A unit filter matches devices placed in it or below, or with a camera there.
  const inUnit = useMemo(() => {
    if (!unitId) return () => true;
    const below = new Set<string>([unitId]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const u of units)
        if (u.parent_id && below.has(u.parent_id) && !below.has(u.id)) {
          below.add(u.id);
          grew = true;
        }
    }
    return (d: Device) => below.has(d.org_unit_id) || d.cameras.some((c) => below.has(c.org_unit_id));
  }, [unitId, units]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return devices.filter(
      (d) =>
        (status === "all" || statusOf(d) === status) &&
        (!vendor || d.vendor === vendor) &&
        inUnit(d) &&
        (!q ||
          `${d.name} ${d.host} ${d.model} ${d.serial} ${d.cameras.map((c) => c.name).join(" ")}`
            .toLowerCase()
            .includes(q)),
    );
  }, [devices, query, status, vendor, inUnit]);

  const vendorsPresent = useMemo(() => [...new Set(devices.map((d) => d.vendor))], [devices]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.devices });
    qc.invalidateQueries({ queryKey: keys.allCameras });
    qc.invalidateQueries({ queryKey: keys.units });
  };
  const removeDevice = useMutation({
    mutationFn: (id: string) => api.deleteDevice(id),
    onSuccess: () => {
      refresh();
      setDialog(null);
      notify(t("devices.deleted"));
    },
  });
  const removeCamera = useMutation({
    mutationFn: (id: string) => api.deleteCamera(id),
    onSuccess: () => {
      refresh();
      setDialog(null);
      notify(t("devices.cameraDeleted"));
    },
  });

  if (!admin) return <Navigate to="/cameras" replace />;

  const toggle = (id: string) =>
    setOpen((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const filtered = query !== "" || status !== "all" || vendor !== "" || unitId !== "";
  const resetFilters = () => {
    setQuery("");
    setStatus("all");
    setVendor("");
    setUnitId("");
  };
  const offline = devices.filter((d) => statusOf(d) === "offline").length;
  const headers = [
    t("devices.colName"),
    t("devices.colType"),
    t("devices.colModel"),
    t("devices.colAddress"),
    t("devices.colUnit"),
    t("devices.colStatus"),
  ];

  const lastSeen = (d: Device) =>
    d.last_seen_at
      ? t("devices.lastSeen", {
          time: new Date(d.last_seen_at).toLocaleString(intlLocale(), { dateStyle: "short", timeStyle: "short" }),
        })
      : "";

  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("devices.title")}</h1>
        {hasData && <span className="muted num">{devices.length}</span>}
        <span className="spacer" />
        <button className="btn btn-ghost" onClick={() => setDialog({ kind: "creds" })}>
          <KeyRound size={16} />
          {t("devices.credentials")}
        </button>
        <button className="btn btn-ghost" onClick={() => setDialog({ kind: "import" })}>
          <FileSpreadsheet size={16} />
          {t("devices.import")}
        </button>
        <button className="btn" onClick={() => setDialog({ kind: "scan" })}>
          <Radar size={16} />
          {t("devices.scanNetwork")}
        </button>
        <button className="btn btn-primary" onClick={() => setDialog({ kind: "add" })}>
          <Plus size={16} />
          {t("devices.add")}
        </button>
      </div>

      {devices.length > 0 && (
        <div className="filters">
          <div className="search grow-search">
            <Search size={15} />
            <input
              className="input"
              placeholder={t("common.search")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div className="segmented" role="group" aria-label={t("devices.colStatus")}>
            {(["all", "online", "offline", "unknown"] as Status[]).map((s) => (
              <button key={s} aria-pressed={status === s} onClick={() => setStatus(s)}>
                {s !== "all" && <i className={`dot ${s}`} />}
                {t(`devices.status.${s}`)}
              </button>
            ))}
          </div>
          <select className="select fit" value={vendor} onChange={(e) => setVendor(e.target.value)}>
            <option value="">{t("devices.allVendors")}</option>
            {vendorsPresent.map((v) => (
              <option key={v} value={v}>
                {t(`devices.vendors.${v}`)}
              </option>
            ))}
          </select>
          <select className="select fit narrow" value={unitId} onChange={(e) => setUnitId(e.target.value)}>
            <option value="">{t("devices.allUnits")}</option>
            {unitOptions.map((u) => (
              <option key={u.id} value={u.id}>
                {" ".repeat(u.depth)}
                {u.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* A failed refresh keeps the last good table and says so above it. */}
      {list.isError && hasData && (
        <div className="card table-alert">
          <ErrorState
            title={t("devices.loadFailed")}
            lastOk={list.dataUpdatedAt}
            onRetry={() => list.refetch()}
            retrying={list.isFetching}
          />
        </div>
      )}

      <div className="card">
        {list.isPending ? (
          <Skeleton rows={6} columns={[64, 96, 180, 96, 110, 72]} headers={headers} />
        ) : list.isError && !hasData ? (
          <ErrorState
            title={t("devices.loadFailed")}
            lastOk={list.dataUpdatedAt}
            onRetry={() => list.refetch()}
            retrying={list.isFetching}
          />
        ) : devices.length === 0 ? (
          <EmptyState
            icon={Router}
            title={t("devices.empty")}
            action={
              <button className="btn btn-primary btn-sm" onClick={() => setDialog({ kind: "add" })}>
                <Plus size={14} />
                {t("devices.add")}
              </button>
            }
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={Search}
            title={t("devices.noMatches")}
            action={
              <button className="btn btn-sm" onClick={resetFilters}>
                {t("states.resetFilters")}
              </button>
            }
          />
        ) : (
          <div className="table-wrap">
            <table className="table devices-table">
              <colgroup>
                <col className="col-caret" />
                <col className="col-name" />
                <col className="col-type" />
                <col className="col-model" />
                <col className="col-address" />
                <col className="col-unit" />
                <col className="col-status" />
                <col className="col-actions" />
              </colgroup>
              <thead>
                <tr>
                  <th />
                  <th>{t("devices.colName")}</th>
                  <th>{t("devices.colType")}</th>
                  <th>{t("devices.colModel")}</th>
                  <th>{t("devices.colAddress")}</th>
                  <th>{t("devices.colUnit")}</th>
                  <th>{t("devices.colStatus")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => {
                  const expanded = open.has(d.id);
                  const single = d.cameras.length === 1 && d.kind === "camera";
                  const st = statusOf(d);
                  const path = unitPath(units, d.org_unit_id);
                  return (
                    <Fragment key={d.id}>
                      <tr
                        className={expanded ? "open" : undefined}
                        onClick={() => toggle(d.id)}
                        aria-expanded={expanded}
                      >
                        <td>
                          <ChevronRight size={15} className={`caret${expanded ? " open" : ""}`} />
                        </td>
                        <td>
                          <span className="device-name">{d.name}</span>
                        </td>
                        <td className="muted">
                          {t(`devices.kind.${d.kind}`)}
                          {d.kind === "recorder" && (
                            <>
                              , <span className="num">{d.cameras.length}</span>
                            </>
                          )}
                        </td>
                        <td className="muted cell-model">
                          {t(`devices.vendors.${d.vendor}`)} {d.model && <span className="num">{d.model}</span>}
                        </td>
                        <td className="num">{d.host}</td>
                        {/* The unit itself; where it sits is in the tooltip. */}
                        <td className="muted cell-unit" title={path}>
                          {unitNames.get(d.org_unit_id)}
                        </td>
                        <td title={lastSeen(d)}>
                          <span className={`status-dot ${st}`}>{t(`devices.status.${st}`)}</span>
                        </td>
                        <td className="actions">
                          <RowActions
                            actions={
                              [
                                single && {
                                  icon: Settings2,
                                  label: t("devices.camera.title"),
                                  onClick: () => setDialog({ kind: "camera", camera: d.cameras[0] }),
                                },
                                d.kind === "recorder" && {
                                  icon: RefreshCw,
                                  label: t("devices.refreshChannels"),
                                  onClick: () => setDialog({ kind: "sync", device: d }),
                                },
                                {
                                  icon: Pencil,
                                  label: t("devices.editDevice"),
                                  onClick: () => setDialog({ kind: "device", device: d }),
                                },
                                {
                                  icon: Trash2,
                                  label: t("common.delete"),
                                  danger: true,
                                  onClick: () => setDialog({ kind: "deleteDevice", device: d }),
                                },
                              ].filter(Boolean) as RowAction[]
                            }
                          />
                        </td>
                      </tr>
                      {expanded &&
                        d.cameras.map((c) => (
                          <tr key={c.id} className="sub-row" onClick={() => setDialog({ kind: "camera", camera: c })}>
                            <td />
                            <td>
                              <span className="channel-no num">{c.channel}</span>
                              <span className={c.enabled ? undefined : "muted"}>{c.name}</span>
                              {c.missing && <span className="badge warn">{t("devices.missing")}</span>}
                            </td>
                            <td colSpan={3}>
                              {c.face_recognition && (
                                <span className="inline-meta">
                                  <ScanFace size={14} aria-hidden />
                                  {t("devices.camera.faceRecognition")}
                                  <DirectionBadge direction={c.direction} />
                                </span>
                              )}
                            </td>
                            <td className="muted cell-unit" title={unitPath(units, c.org_unit_id)}>
                              {unitNames.get(c.org_unit_id)}
                            </td>
                            <td />
                            <td className="actions">
                              <RowActions
                                actions={[
                                  {
                                    icon: Settings2,
                                    label: t("devices.camera.title"),
                                    onClick: () => setDialog({ kind: "camera", camera: c }),
                                  },
                                  {
                                    icon: Trash2,
                                    label: t("common.delete"),
                                    danger: true,
                                    onClick: () => setDialog({ kind: "deleteCamera", camera: c }),
                                  },
                                ]}
                              />
                            </td>
                          </tr>
                        ))}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            <div className="table-foot">
              <span>{t("devices.shownOf", { shown: rows.length, count: devices.length })}</span>
              {offline > 0 && (
                <span className="status-dot offline">
                  {t("devices.status.offline")}: <span className="num">{offline}</span>
                </span>
              )}
              {filtered && (
                <button className="btn btn-ghost btn-sm" onClick={resetFilters}>
                  {t("states.resetFilters")}
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {dialog?.kind === "add" && (
        <AddDeviceModal defaultUnitId={unitId || null} preset={dialog.preset} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === "scan" && (
        <ScanModal
          defaultUnitId={unitId || null}
          onAddOne={(f, v) => setDialog({ kind: "add", preset: { vendor: v, host: f.ip, http_port: f.http_port } })}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "import" && <ImportModal onClose={() => setDialog(null)} />}
      {dialog?.kind === "creds" && <CredentialsModal onClose={() => setDialog(null)} />}
      {dialog?.kind === "device" && <DeviceModal device={dialog.device} onClose={() => setDialog(null)} />}
      {dialog?.kind === "sync" && <SyncModal device={dialog.device} onClose={() => setDialog(null)} />}
      {dialog?.kind === "camera" && <CameraModal camera={dialog.camera} onClose={() => setDialog(null)} />}
      {dialog?.kind === "deleteDevice" && (
        <Confirm
          text={t("devices.deleteConfirm", { name: dialog.device.name, count: dialog.device.cameras.length })}
          confirmLabel={t("common.delete")}
          onConfirm={() => removeDevice.mutate(dialog.device.id)}
          onClose={() => setDialog(null)}
          busy={removeDevice.isPending}
          error={removeDevice.error ? errorText(t, removeDevice.error) : undefined}
        />
      )}
      {dialog?.kind === "deleteCamera" && (
        <Confirm
          text={t("devices.deleteCameraConfirm", { name: dialog.camera.name })}
          confirmLabel={t("common.delete")}
          onConfirm={() => removeCamera.mutate(dialog.camera.id)}
          onClose={() => setDialog(null)}
          busy={removeCamera.isPending}
          error={removeCamera.error ? errorText(t, removeCamera.error) : undefined}
        />
      )}
    </div>
  );
}
