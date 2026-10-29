import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { keys, useUnits } from "../../api/queries";
import type { Device } from "../../api/types";
import { CredentialPicker, type CredentialValue } from "../../components/CredentialPicker";
import { Modal } from "../../components/Modal";
import { UnitSelect } from "../../components/UnitSelect";
import { errorText } from "../../lib/errors";
import { useUi } from "../../lib/store";
import { vendorMeta } from "../../lib/vendors";

/** Name, place, address and login of an existing device. */
export function DeviceModal({ device, onClose }: { device: Device; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const notify = useUi((s) => s.notify);
  const { data: units = [] } = useUnits();
  const meta = vendorMeta(device.vendor);
  const [name, setName] = useState(device.name);
  const [unitId, setUnitId] = useState(device.org_unit_id);
  const [host, setHost] = useState(device.host);
  const [port, setPort] = useState(device.rtsp_port);
  const [httpPort, setHttpPort] = useState(device.http_port);
  const [cred, setCred] = useState<CredentialValue>({
    credential_id: device.credential_id,
    username: device.username,
    password: "",
  });
  const [error, setError] = useState("");

  const save = useMutation({
    mutationFn: () =>
      api.updateDevice(device.id, {
        name: name.trim(),
        org_unit_id: unitId,
        host: host.trim(),
        rtsp_port: port,
        http_port: httpPort,
        ...cred,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.devices });
      qc.invalidateQueries({ queryKey: keys.credentials });
      notify(t("devices.saved"));
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
      title={t("devices.editDevice")}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button className="btn btn-primary" type="submit" form="device-edit" disabled={save.isPending}>
            {t("common.save")}
          </button>
        </>
      }
    >
      <form id="device-edit" className="form-grid" onSubmit={submit}>
        <label className="field">
          <span>{t("devices.deviceName")}</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
        </label>
        <label className="field">
          <span>{t("devices.deviceUnit")}</span>
          <UnitSelect units={units} value={unitId} onChange={setUnitId} required />
        </label>
        {!meta.url && (
          <>
            <label className="field">
              <span>{t("devices.host")}</span>
              <input className="input num" value={host} onChange={(e) => setHost(e.target.value)} required />
            </label>
            <div className="form-grid gap-3">
              <label className="field">
                <span>{device.vendor === "dvrip" ? t("devices.dvripPort") : t("devices.rtspPort")}</span>
                <input className="input num" type="number" min={1} max={65535} value={port} onChange={(e) => setPort(Number(e.target.value))} />
              </label>
              {meta.web && (
                <label className="field">
                  <span>{t("devices.httpPort")}</span>
                  <input className="input num" type="number" min={1} max={65535} value={httpPort} onChange={(e) => setHttpPort(Number(e.target.value))} />
                </label>
              )}
            </div>
          </>
        )}
        <CredentialPicker value={cred} onChange={setCred} keepHint />
        {(device.model || device.serial) && (
          <p className="lead wide">
            {[device.model, device.serial, device.firmware].filter(Boolean).join(", ")}
          </p>
        )}
        {error && <p className="form-error" role="alert">{error}</p>}
      </form>
    </Modal>
  );
}
