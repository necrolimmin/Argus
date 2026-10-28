import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, TriangleAlert } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { keys, useUnits } from "../../api/queries";
import type { Connection, ProbeResult, Vendor } from "../../api/types";
import { CredentialPicker, type CredentialValue } from "../../components/CredentialPicker";
import { Modal } from "../../components/Modal";
import { UnitSelect } from "../../components/UnitSelect";
import { codeText, errorText } from "../../lib/errors";
import { useUi } from "../../lib/store";
import { VENDORS, vendorMeta } from "../../lib/vendors";
import { ProbeSummary } from "./ProbeSummary";

interface ChannelPick {
  selected: boolean;
  name: string;
  unit: string; // "" = same as the device
}

interface Props {
  defaultUnitId?: string | null;
  /** Pre-filled from a scan result. */
  preset?: { vendor: Vendor; host: string; http_port?: number | null };
  onClose: () => void;
}

export function AddDeviceModal({ defaultUnitId, preset, onClose }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const notify = useUi((s) => s.notify);
  const { data: units = [] } = useUnits();

  const [vendor, setVendor] = useState<Vendor>(preset?.vendor ?? "hikvision");
  const [host, setHost] = useState(preset?.host ?? "");
  const [port, setPort] = useState(vendorMeta(preset?.vendor ?? "hikvision").defaultPort);
  const [httpPort, setHttpPort] = useState(preset?.http_port ?? 80);
  const [rtspMain, setRtspMain] = useState("");
  const [rtspSub, setRtspSub] = useState("");
  const [channelCount, setChannelCount] = useState(1);
  const [cred, setCred] = useState<CredentialValue>({ credential_id: null, username: "admin", password: "" });

  const [result, setResult] = useState<ProbeResult | null>(null);
  const [name, setName] = useState("");
  const [unitId, setUnitId] = useState(defaultUnitId ?? "");
  const [picks, setPicks] = useState<Record<number, ChannelPick>>({});
  const [error, setError] = useState("");

  const meta = vendorMeta(vendor);

  const connection = (): Connection => ({
    vendor,
    host: meta.url ? "" : host.trim(),
    rtsp_port: port,
    http_port: httpPort,
    ...cred,
    rtsp_main: meta.url ? rtspMain.trim() : "",
    rtsp_sub: meta.url ? rtspSub.trim() : "",
    channel_count: meta.askChannels ? channelCount : null,
  });

  // Any change to how we connect makes the last check stale.
  const touch = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v);
    setResult(null);
    setError("");
  };

  const check = useMutation({
    mutationFn: () => api.probeDevice(connection()),
    onSuccess: (res) => {
      setResult(res);
      setError("");
      // The device told us its real RTSP port; keep it for saving.
      if (res.rtsp_port) setPort(res.rtsp_port);
      if (!res.ok) return;
      const base = res.name || [res.model, meta.url ? "" : host.trim()].filter(Boolean).join(" ") || host.trim();
      setName((n) => n || base);
      const next: Record<number, ChannelPick> = {};
      for (const c of res.channels) {
        next[c.channel] = {
          selected: !c.camera_id && !c.duplicate_of,
          name: c.name || (res.channels.length > 1 ? `${base} — ${c.channel}` : base),
          unit: "",
        };
      }
      setPicks(next);
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const chosen = useMemo(
    () => (result?.channels ?? []).filter((c) => picks[c.channel]?.selected),
    [result, picks],
  );

  const save = useMutation({
    mutationFn: () => {
      const single = result!.channels.length === 1;
      return api.createDevice({
        ...connection(),
        name: name.trim(),
        kind: result!.kind,
        org_unit_id: unitId,
        model: result!.model,
        serial: result!.serial,
        mac: result!.mac,
        firmware: result!.firmware,
        channels: chosen.map((c) => ({
          channel: c.channel,
          name: (single ? name : picks[c.channel].name).trim(),
          org_unit_id: picks[c.channel].unit || null,
          rtsp_main: c.rtsp_main,
          rtsp_sub: c.rtsp_sub,
        })),
      });
    },
    onSuccess: (dev) => {
      qc.invalidateQueries({ queryKey: keys.devices });
      qc.invalidateQueries({ queryKey: keys.allCameras });
      qc.invalidateQueries({ queryKey: keys.units });
      notify(t("devices.added", { count: dev.cameras.length }));
      onClose();
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (result?.ok) save.mutate();
    else check.mutate();
  };

  const multi = (result?.channels.length ?? 0) > 1;
  const allSelected = multi && result!.channels.every((c) => picks[c.channel]?.selected);
  const setPick = (ch: number, patch: Partial<ChannelPick>) =>
    setPicks((p) => ({ ...p, [ch]: { ...p[ch], ...patch } }));

  return (
    <Modal
      title={t("devices.newDevice")}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button className="btn" type="button" onClick={() => check.mutate()} disabled={check.isPending}>
            {check.isPending ? t("devices.checking") : t("devices.check")}
          </button>
          <button
            className="btn btn-primary"
            type="submit"
            form="device-form"
            disabled={!result?.ok || !chosen.length || !unitId || save.isPending}
          >
            {t("common.add")}
          </button>
        </>
      }
    >
      <form id="device-form" className="form-grid" onSubmit={submit}>
        <div className="field wide">
          <span>{t("devices.vendor")}</span>
          <div className="vendor-grid" role="group">
            {VENDORS.map((v) => (
              <button
                type="button"
                key={v.id}
                aria-pressed={vendor === v.id}
                onClick={() => {
                  touch(setVendor)(v.id);
                  setPort(v.defaultPort);
                }}
              >
                {t(`devices.vendors.${v.id}`)}
              </button>
            ))}
          </div>
          {t(`devices.vendorHints.${vendor}`, { defaultValue: "" }) && (
            <span className="hint">{t(`devices.vendorHints.${vendor}`)}</span>
          )}
        </div>

        {meta.url ? (
          <>
            <label className="field wide">
              <span>{vendor === "http" ? t("devices.httpUrl") : t("devices.rtspMain")}</span>
              <input
                className="input"
                value={rtspMain}
                onChange={(e) => touch(setRtspMain)(e.target.value)}
                placeholder={vendor === "http" ? "http://192.168.1.20/video.mjpg" : "rtsp://192.168.1.20:554/stream1"}
                required
              />
            </label>
            {vendor === "rtsp" && (
              <label className="field wide">
                <span>
                  {t("devices.rtspSub")} <span className="muted">({t("common.optional")})</span>
                </span>
                <input className="input" value={rtspSub} onChange={(e) => touch(setRtspSub)(e.target.value)} />
              </label>
            )}
          </>
        ) : (
          <>
            <label className="field">
              <span>{t("devices.host")}</span>
              <input
                className="input num"
                value={host}
                onChange={(e) => touch(setHost)(e.target.value)}
                placeholder="192.168.1.64"
                required
                autoFocus
              />
            </label>
            <div className="form-grid" style={{ gap: 12 }}>
              <label className="field">
                <span>{vendor === "dvrip" ? t("devices.dvripPort") : t("devices.rtspPort")}</span>
                <input className="input num" type="number" min={1} max={65535} value={port}
                  onChange={(e) => touch(setPort)(Number(e.target.value))} />
              </label>
              {meta.web ? (
                <label className="field">
                  <span>{t("devices.httpPort")}</span>
                  <input className="input num" type="number" min={1} max={65535} value={httpPort}
                    onChange={(e) => touch(setHttpPort)(Number(e.target.value))} />
                </label>
              ) : meta.askChannels ? (
                <label className="field">
                  <span>{t("devices.channelCount")}</span>
                  <input className="input num" type="number" min={1} max={256} value={channelCount}
                    onChange={(e) => touch(setChannelCount)(Number(e.target.value))} />
                </label>
              ) : null}
            </div>
          </>
        )}

        <CredentialPicker value={cred} onChange={touch(setCred)} />

        {error && <p className="form-error" role="alert">{error}</p>}

        {result && !result.ok && (
          <div className="probe-error wide" role="alert">
            <TriangleAlert size={18} />
            <span>{codeText(t, result.error)}</span>
          </div>
        )}

        {result?.ok && (
          <>
            <div className="wide">
              <div className="probe-ok">
                <CircleCheck size={18} />
                {t("devices.checkOk")}
              </div>
              <ProbeSummary result={result} />
            </div>

            <label className="field">
              <span>{t("devices.deviceName")}</span>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
            </label>
            <label className="field">
              <span>{t("devices.deviceUnit")}</span>
              <UnitSelect units={units} value={unitId} onChange={setUnitId} required />
            </label>

            {multi && (
              <div className="form-section">
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <strong>{t("devices.channels")}</strong>
                  <span className="muted num">
                    {chosen.length}/{result.channels.length}
                  </span>
                  <span style={{ flex: 1 }} />
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={(e) =>
                        setPicks((p) =>
                          Object.fromEntries(
                            Object.entries(p).map(([k, v]) => [k, { ...v, selected: e.target.checked }]),
                          ),
                        )
                      }
                    />
                    <span>{t("devices.selectAll")}</span>
                  </label>
                </div>
                <div className="channel-list">
                  {result.channels.map((c) => {
                    const pick = picks[c.channel];
                    const taken = Boolean(c.camera_id);
                    return (
                      <div key={c.channel} className={`channel-row${pick?.selected ? "" : " off"}`}>
                        <input
                          type="checkbox"
                          checked={pick?.selected ?? false}
                          disabled={taken}
                          onChange={(e) => setPick(c.channel, { selected: e.target.checked })}
                          aria-label={`${c.channel}`}
                        />
                        <span className="channel-no num">{c.channel}</span>
                        <input
                          className="input"
                          value={pick?.name ?? ""}
                          onChange={(e) => setPick(c.channel, { name: e.target.value })}
                          disabled={!pick?.selected}
                          maxLength={200}
                          aria-label={t("devices.channelName")}
                        />
                        <select
                          className="select"
                          value={pick?.unit ?? ""}
                          onChange={(e) => setPick(c.channel, { unit: e.target.value })}
                          disabled={!pick?.selected}
                          aria-label={t("devices.channelUnit")}
                        >
                          <option value="">{t("devices.sameAsDevice")}</option>
                          {units.map((u) => (
                            <option key={u.id} value={u.id}>
                              {u.name}
                            </option>
                          ))}
                        </select>
                        {c.duplicate_of && (
                          <span className="channel-note">{t("devices.duplicateChannel", { name: c.duplicate_of })}</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </>
        )}
      </form>
    </Modal>
  );
}
