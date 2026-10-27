import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { keys } from "../../api/queries";
import type { Device } from "../../api/types";
import { Modal } from "../../components/Modal";
import { codeText, errorText } from "../../lib/errors";
import { useUi } from "../../lib/store";
import { ProbeSummary } from "./ProbeSummary";

/** Re-reads a recorder and offers the channels Argus does not have yet. */
export function SyncModal({ device, onClose }: { device: Device; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const notify = useUi((s) => s.notify);
  const [picked, setPicked] = useState<Record<number, string>>({});

  const sync = useQuery({
    queryKey: ["sync", device.id],
    queryFn: async () => {
      const res = await api.syncDevice(device.id);
      qc.invalidateQueries({ queryKey: keys.devices });
      const fresh = res.channels.filter((c) => !c.camera_id);
      setPicked(Object.fromEntries(fresh.map((c) => [c.channel, c.name || `${device.name} — ${c.channel}`])));
      return res;
    },
    gcTime: 0,
    retry: false,
  });

  const fresh = (sync.data?.channels ?? []).filter((c) => !c.camera_id);
  const missing = device.cameras.filter((c) => !(sync.data?.channels ?? []).some((x) => x.channel === c.channel));

  const add = useMutation({
    mutationFn: () =>
      api.addChannels(
        device.id,
        Object.entries(picked).map(([channel, name]) => ({
          channel: Number(channel),
          name: name.trim() || `${device.name} — ${channel}`,
          org_unit_id: null,
          rtsp_main: fresh.find((c) => c.channel === Number(channel))?.rtsp_main ?? "",
          rtsp_sub: fresh.find((c) => c.channel === Number(channel))?.rtsp_sub ?? "",
        })),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.devices });
      qc.invalidateQueries({ queryKey: keys.allCameras });
      notify(t("devices.added", { count: Object.keys(picked).length }));
      onClose();
    },
  });

  return (
    <Modal
      title={`${t("devices.sync.title")}: ${device.name}`}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            {t("common.close")}
          </button>
          {fresh.length > 0 && (
            <button className="btn btn-primary" onClick={() => add.mutate()} disabled={!Object.keys(picked).length || add.isPending}>
              {t("devices.sync.add")}
            </button>
          )}
        </>
      }
    >
      {sync.isPending && <p className="muted">{t("devices.checking")}</p>}
      {sync.isError && <p className="form-error">{errorText(t, sync.error)}</p>}
      {sync.data && !sync.data.ok && (
        <div className="probe-error" role="alert">
          <TriangleAlert size={18} />
          <span>{codeText(t, sync.data.error)}</span>
        </div>
      )}
      {sync.data?.ok && (
        <div style={{ display: "grid", gap: 16 }}>
          <ProbeSummary result={sync.data} />
          {missing.length > 0 && device.kind === "recorder" && (
            <p className="probe-warn">
              <TriangleAlert size={15} />
              {t("devices.sync.missingCount", { count: missing.length })}
            </p>
          )}
          <div>
            <strong>{t("devices.sync.newChannels")}</strong>
            {fresh.length === 0 ? (
              <p className="muted">{t("devices.sync.none")}</p>
            ) : (
              <div className="channel-list" style={{ marginTop: 8 }}>
                {fresh.map((c) => {
                  const on = c.channel in picked;
                  return (
                    <div key={c.channel} className={`channel-row${on ? "" : " off"}`}>
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={(e) =>
                          setPicked((p) => {
                            const next = { ...p };
                            if (e.target.checked) next[c.channel] = c.name || `${device.name} — ${c.channel}`;
                            else delete next[c.channel];
                            return next;
                          })
                        }
                        aria-label={`${c.channel}`}
                      />
                      <span className="channel-no num">{c.channel}</span>
                      <input
                        className="input"
                        value={picked[c.channel] ?? c.name}
                        disabled={!on}
                        onChange={(e) => setPicked((p) => ({ ...p, [c.channel]: e.target.value }))}
                        aria-label={t("devices.channelName")}
                      />
                      {c.duplicate_of && <span className="channel-note">{t("devices.duplicateChannel", { name: c.duplicate_of })}</span>}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
