import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Download, Eye } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { keys, useUnits } from "../../api/queries";
import type { Device, IsupInfo } from "../../api/types";
import { Modal } from "../../components/Modal";
import { UnitSelect } from "../../components/UnitSelect";
import { errorText } from "../../lib/errors";

export function useIsupInfo() {
  return useQuery({ queryKey: ["isup-info"], queryFn: api.isupInfo, refetchInterval: 10_000 });
}

function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation();
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="icon-btn sm"
      title={done ? t("devices.isup.copied") : t("devices.isup.copy")}
      aria-label={t("devices.isup.copy")}
      onClick={() => {
        navigator.clipboard?.writeText(text).catch(() => {});
        setDone(true);
        window.setTimeout(() => setDone(false), 1500);
      }}
    >
      {done ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
}

/** Server address and port, the same for every device. */
export function IsupServer({ info }: { info?: IsupInfo }) {
  const { t } = useTranslation();
  if (!info) return null;
  return (
    <>
      {!info.enabled && <p className="notice">{t("devices.isup.notEnabled")}</p>}
      {info.enabled && !info.bridge && <p className="notice">{t("devices.isup.bridgeDown")}</p>}
      <dl className="isup-sheet">
        <div>
          <dt>{t("devices.isup.server")}</dt>
          <dd className="num">
            {info.address || "—"}
            {info.address && <CopyButton text={info.address} />}
          </dd>
        </div>
        <div>
          <dt>{t("devices.isup.port")}</dt>
          <dd className="num">{info.port}</dd>
        </div>
        <div>
          <dt>{t("devices.isup.protocol")}</dt>
          <dd>ISUP 5.0</dd>
        </div>
      </dl>
    </>
  );
}

/** What the installer does on the device, in the device's own menu terms. */
export function IsupSteps() {
  const { t } = useTranslation();
  return (
    <ol className="import-steps isup-steps">
      {[1, 2, 3, 4].map((n) => (
        <li key={n}>
          <span>{t(`devices.isup.step${n}`)}</span>
        </li>
      ))}
    </ol>
  );
}

/** Device ID and key of one device, the key shown only when asked for. */
export function IsupDeviceAccess({ device }: { device: Device }) {
  const { t } = useTranslation();
  const key = useMutation({ mutationFn: () => api.isupKey(device.id) });
  return (
    <dl className="isup-sheet">
      <div>
        <dt>{t("devices.isup.deviceId")}</dt>
        <dd className="num">
          {device.isup_id}
          <CopyButton text={device.isup_id ?? ""} />
        </dd>
      </div>
      <div>
        <dt>{t("devices.isup.key")}</dt>
        <dd className="num">
          {key.data ? (
            <>
              {key.data.key}
              <CopyButton text={key.data.key} />
            </>
          ) : (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => key.mutate()} disabled={key.isPending}>
              <Eye size={14} />
              {t("devices.isup.showKey")}
            </button>
          )}
        </dd>
      </div>
    </dl>
  );
}

function csv(rows: { device: Device; key: string }[], info?: IsupInfo) {
  const head = ["Name", "Device ID", "Encryption Key", "Server", "Port"];
  const lines = rows.map((r) => [r.device.name, r.device.isup_id ?? "", r.key, info?.address ?? "", String(info?.port ?? "")]);
  return [head, ...lines].map((l) => l.map((v) => `"${v.replace(/"/g, '""')}"`).join(",")).join("\r\n");
}

/**
 * Hikvision devices that will connect to Argus by themselves (ISUP 5.0).
 * Argus makes a Device ID and key for each; the installer types them into
 * the device, and the device's cameras appear here once it connects.
 */
export function IsupModal({
  defaultUnitId,
  deviceId,
  onClose,
}: {
  defaultUnitId: string | null;
  /** A device that already tried to connect with this ID: add it as it is. */
  deviceId?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: units = [] } = useUnits();
  const info = useIsupInfo();
  const [unitId, setUnitId] = useState(defaultUnitId ?? "");
  const [count, setCount] = useState(1);
  const [name, setName] = useState("");
  const [own, setOwn] = useState(!!deviceId);
  const [ownId, setOwnId] = useState(deviceId ?? "");
  const [ownKey, setOwnKey] = useState("");
  const [error, setError] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.isupCreate({
        org_unit_id: unitId,
        count: own ? 1 : count,
        name: name.trim(),
        device_id: own ? ownId.trim() : "",
        key: own ? ownKey.trim() : "",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.devices });
      setError("");
    },
    onError: (e) => setError(errorText(t, e)),
  });
  const made = create.data;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };

  const download = () => {
    if (!made) return;
    const url = URL.createObjectURL(new Blob(["﻿" + csv(made, info.data)], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "argus-isup.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Modal
      title={t("devices.isup.title")}
      onClose={onClose}
      wide
      footer={
        made ? (
          <>
            <button className="btn btn-ghost" onClick={download}>
              <Download size={16} />
              {t("devices.isup.download")}
            </button>
            <button className="btn btn-primary" onClick={onClose}>
              {t("common.close")}
            </button>
          </>
        ) : (
          <>
            <button className="btn btn-ghost" onClick={onClose}>
              {t("common.cancel")}
            </button>
            <button className="btn btn-primary" type="submit" form="isup-form" disabled={create.isPending || !unitId}>
              {t("devices.isup.create")}
            </button>
          </>
        )
      }
    >
      {!made ? (
        <form id="isup-form" className="form-grid" onSubmit={submit}>
          <p className="lead wide">{t("devices.isup.lead")}</p>
          <label className="field">
            <span>{t("devices.deviceUnit")}</span>
            <UnitSelect units={units} value={unitId} onChange={setUnitId} required />
          </label>
          <label className="field">
            <span>{t("devices.isup.name")}</span>
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("devices.isup.namePlaceholder")}
              maxLength={200}
            />
          </label>
          {!own && (
            <label className="field">
              <span>{t("devices.isup.count")}</span>
              <input
                className="input num"
                type="number"
                min={1}
                max={50}
                value={count}
                onChange={(e) => setCount(Math.min(50, Math.max(1, Number(e.target.value) || 1)))}
              />
              <span className="hint">{t("devices.isup.countHint")}</span>
            </label>
          )}
          <label className="check wide">
            <input type="checkbox" checked={own} onChange={(e) => setOwn(e.target.checked)} />
            <span>{t("devices.isup.own")}</span>
          </label>
          {own && (
            <>
              <label className="field">
                <span>{t("devices.isup.deviceId")}</span>
                <input
                  className="input num"
                  value={ownId}
                  onChange={(e) => setOwnId(e.target.value)}
                  required
                  maxLength={64}
                  pattern="[A-Za-z0-9_\-]+"
                />
              </label>
              <label className="field">
                <span>{t("devices.isup.key")}</span>
                <input
                  className="input num"
                  value={ownKey}
                  onChange={(e) => setOwnKey(e.target.value)}
                  required
                  minLength={8}
                  maxLength={32}
                  pattern="[A-Za-z0-9]+"
                />
              </label>
            </>
          )}
          {error && (
            <p className="form-error wide" role="alert">
              {error}
            </p>
          )}
        </form>
      ) : (
        <div className="stack">
          <p className="lead">{t("devices.isup.done", { count: made.length })}</p>
          <IsupServer info={info.data} />
          <div className="table-wrap scroll-box">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("devices.colName")}</th>
                  <th>{t("devices.isup.deviceId")}</th>
                  <th>{t("devices.isup.key")}</th>
                </tr>
              </thead>
              <tbody>
                {made.map((m) => (
                  <tr key={m.device.id} style={{ cursor: "default" }}>
                    <td>{m.device.name}</td>
                    <td className="num">
                      {m.device.isup_id} <CopyButton text={m.device.isup_id ?? ""} />
                    </td>
                    <td className="num">
                      {m.key} <CopyButton text={m.key} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <IsupSteps />
        </div>
      )}
    </Modal>
  );
}
