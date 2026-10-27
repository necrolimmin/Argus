import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { keys, useUnits } from "../api/queries";
import type { Camera, CameraSettings, Direction, Quality, ScheduleWindow } from "../api/types";
import { Modal } from "../components/Modal";
import { UnitSelect } from "../components/UnitSelect";
import { errorText } from "../lib/errors";
import { useUi } from "../lib/store";

const DEFAULT_WINDOW: ScheduleWindow = { days: [1, 2, 3, 4, 5, 6], start: "07:00", end: "20:00" };

/** Settings of one channel. Address and login are edited on the device. */
export function CameraModal({ camera, onClose }: { camera: Camera; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const notify = useUi((s) => s.notify);
  const { data: units = [] } = useUnits();
  const [form, setForm] = useState<CameraSettings>(() => ({
    name: camera.name,
    org_unit_id: camera.org_unit_id,
    face_recognition: camera.face_recognition,
    direction: camera.direction,
    schedule: camera.schedule,
    recognition_stream: camera.recognition_stream,
    enabled: camera.enabled,
    rtsp_main: camera.rtsp_main,
    rtsp_sub: camera.rtsp_sub,
  }));
  const [showStreams, setShowStreams] = useState(Boolean(camera.rtsp_main || camera.rtsp_sub));
  const [error, setError] = useState("");
  const weekdays = t("devices.camera.weekdays", { returnObjects: true }) as string[];

  const set = <K extends keyof CameraSettings>(key: K, value: CameraSettings[K]) =>
    setForm((f) => ({ ...f, [key]: value }));
  const win = form.schedule[0];
  const setWin = (patch: Partial<ScheduleWindow>) => set("schedule", [{ ...(win ?? DEFAULT_WINDOW), ...patch }]);

  const save = useMutation({
    mutationFn: () => api.updateCamera(camera.id, form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.devices });
      qc.invalidateQueries({ queryKey: keys.allCameras });
      qc.invalidateQueries({ queryKey: keys.units });
      notify(t("devices.camera.saved"));
      onClose();
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };

  return (
    <Modal
      title={t("devices.camera.title")}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button className="btn btn-primary" type="submit" form="camera-form" disabled={save.isPending}>
            {t("common.save")}
          </button>
        </>
      }
    >
      <form id="camera-form" className="form-grid" onSubmit={submit}>
        <label className="field">
          <span>{t("devices.channelName")}</span>
          <input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} required maxLength={200} />
        </label>
        <label className="field">
          <span>{t("devices.channelUnit")}</span>
          <UnitSelect units={units} value={form.org_unit_id} onChange={(v) => set("org_unit_id", v)} required />
        </label>

        <div className="form-section">
          <label className="check">
            <input type="checkbox" checked={form.face_recognition} onChange={(e) => set("face_recognition", e.target.checked)} />
            <span>
              {t("devices.camera.faceRecognition")}
              <small>{t("devices.camera.faceHint")}</small>
            </span>
          </label>

          {form.face_recognition && (
            <>
              <div className="field">
                <span>{t("devices.camera.direction")}</span>
                <div className="segmented" role="group">
                  {(["entry", "exit", "none"] as Direction[]).map((d) => (
                    <button type="button" key={d} aria-pressed={form.direction === d} onClick={() => set("direction", d)}>
                      {t(`direction.${d}`)}
                    </button>
                  ))}
                </div>
              </div>

              <div className="field">
                <span>{t("devices.camera.schedule")}</span>
                <div className="segmented" role="group">
                  <button type="button" aria-pressed={!win} onClick={() => set("schedule", [])}>
                    {t("devices.camera.scheduleAlways")}
                  </button>
                  <button type="button" aria-pressed={!!win} onClick={() => setWin({})}>
                    {t("devices.camera.scheduleCustom")}
                  </button>
                </div>
              </div>

              {win && (
                <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "end" }}>
                  <div className="field">
                    <span>{t("devices.camera.days")}</span>
                    <div className="segmented" role="group">
                      {weekdays.map((label, i) => {
                        const day = i + 1;
                        const on = win.days.includes(day);
                        return (
                          <button
                            type="button"
                            key={day}
                            aria-pressed={on}
                            onClick={() => {
                              const days = on ? win.days.filter((d) => d !== day) : [...win.days, day].sort();
                              if (days.length) setWin({ days });
                            }}
                          >
                            {label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <label className="field">
                    <span>{t("devices.camera.from")}</span>
                    <input className="input num" type="time" value={win.start} onChange={(e) => setWin({ start: e.target.value })} required />
                  </label>
                  <label className="field">
                    <span>{t("devices.camera.to")}</span>
                    <input className="input num" type="time" value={win.end} onChange={(e) => setWin({ end: e.target.value })} required />
                  </label>
                </div>
              )}

              <div className="field">
                <span>{t("devices.camera.recognitionStream")}</span>
                <div className="segmented" role="group">
                  {(["sub", "main"] as Quality[]).map((q) => (
                    <button type="button" key={q} aria-pressed={form.recognition_stream === q} onClick={() => set("recognition_stream", q)}>
                      {t(`devices.camera.streams.${q}`)}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>

        <div className="form-section">
          <label className="check">
            <input type="checkbox" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
            <span>{t("devices.camera.enabled")}</span>
          </label>
          <label className="check">
            <input type="checkbox" checked={showStreams} onChange={(e) => setShowStreams(e.target.checked)} />
            <span>
              {t("devices.camera.ownStreams")}
              <small>{t("devices.camera.ownStreamsHint")}</small>
            </span>
          </label>
          {showStreams && (
            <>
              <label className="field">
                <span>{t("devices.rtspMain")}</span>
                <input className="input" value={form.rtsp_main} onChange={(e) => set("rtsp_main", e.target.value.trim())} placeholder="rtsp://…" />
              </label>
              <label className="field">
                <span>
                  {t("devices.rtspSub")} <span className="muted">({t("common.optional")})</span>
                </span>
                <input className="input" value={form.rtsp_sub} onChange={(e) => set("rtsp_sub", e.target.value.trim())} />
              </label>
            </>
          )}
        </div>

        {error && <p className="form-error" role="alert">{error}</p>}
      </form>
    </Modal>
  );
}
