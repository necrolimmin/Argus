import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Trash2 } from "lucide-react";
import { type FormEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { keys, useUnits } from "../api/queries";
import type { Employee, EmployeeInput, FaceEvent } from "../api/types";
import { errorText } from "../lib/errors";
import { useUi } from "../lib/store";
import { Modal } from "./Modal";
import { UnitSelect } from "./UnitSelect";

const MAX_PHOTOS = 5;

interface Props {
  employee?: Employee;
  /** Unknown face the new employee is created from. */
  fromEvent?: FaceEvent;
  defaultUnitId?: string | null;
  onSaved?: (employee: Employee) => void;
  onClose: () => void;
}

export function EmployeeModal({ employee: initial, fromEvent, defaultUnitId, onSaved, onClose }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const notify = useUi((s) => s.notify);
  const { data: units = [] } = useUnits();
  const [employee, setEmployee] = useState<Employee | undefined>(initial);
  const [form, setForm] = useState<EmployeeInput>(() => ({
    full_name: initial?.full_name ?? "",
    personnel_number: initial?.personnel_number ?? "",
    position: initial?.position ?? "",
    phone: initial?.phone ?? "",
    org_unit_id: initial?.org_unit_id ?? defaultUnitId ?? "",
    is_active: initial?.is_active ?? true,
  }));
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const set = <K extends keyof EmployeeInput>(key: K, value: EmployeeInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.employees });
    qc.invalidateQueries({ queryKey: keys.units });
  };

  const save = useMutation({
    mutationFn: () => {
      if (employee) return api.updateEmployee(employee.id, form);
      if (fromEvent) return api.employeeFromEvent(fromEvent.id, form);
      return api.createEmployee(form);
    },
    onSuccess: (saved) => {
      refresh();
      setError("");
      onSaved?.(saved);
      if (employee || fromEvent) {
        notify(t(employee ? "employee.saved" : "employee.created"));
        onClose();
      } else {
        // Stay open so photos can be added right away.
        setEmployee(saved);
        notify(t("employee.created"));
      }
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadPhoto(employee!.id, file),
    onSuccess: (saved) => {
      setEmployee(saved);
      setError("");
      refresh();
      notify(t("employee.photoAdded"));
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const removePhoto = useMutation({
    mutationFn: (photoId: string) => api.deletePhoto(employee!.id, photoId),
    onSuccess: (saved) => {
      setEmployee(saved);
      refresh();
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };

  const photos = employee?.photos ?? [];

  return (
    <Modal
      title={employee ? t("employee.editTitle") : t("employee.newTitle")}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            {t(employee && !initial ? "common.close" : "common.cancel")}
          </button>
          <button className="btn btn-primary" type="submit" form="employee-form" disabled={save.isPending}>
            {t("common.save")}
          </button>
        </>
      }
    >
      <form id="employee-form" className="form-grid" onSubmit={submit}>
        <label className="field wide">
          <span>{t("employee.fullName")}</span>
          <input className="input" value={form.full_name} onChange={(e) => set("full_name", e.target.value)} required maxLength={200} />
        </label>
        <label className="field">
          <span>{t("employee.personnelNumber")}</span>
          <input className="input" value={form.personnel_number ?? ""} onChange={(e) => set("personnel_number", e.target.value)} maxLength={50} />
        </label>
        <label className="field">
          <span>{t("employee.position")}</span>
          <input className="input" value={form.position} onChange={(e) => set("position", e.target.value)} maxLength={200} />
        </label>
        <label className="field">
          <span>{t("employee.phone")}</span>
          <input className="input" type="tel" value={form.phone} onChange={(e) => set("phone", e.target.value)} maxLength={50} />
        </label>
        <label className="field">
          <span>{t("employee.unit")}</span>
          <UnitSelect units={units} value={form.org_unit_id} onChange={(v) => set("org_unit_id", v)} required />
        </label>
        <label className="check wide">
          <input type="checkbox" checked={form.is_active} onChange={(e) => set("is_active", e.target.checked)} />
          <span>{t("employee.active")}</span>
        </label>

        <div className="form-section">
          <div>
            <strong>{t("employee.photos")}</strong>
            <div className="muted text-sm">
              {t("employee.photosHint")}
            </div>
          </div>
          {fromEvent ? (
            <div className="photos">
              <div className="photo">
                <img src={fromEvent.face_url || fromEvent.image_url} alt="" />
              </div>
            </div>
          ) : employee ? (
            <>
              <div className="photos">
                {photos.map((p) => (
                  <div className="photo" key={p.id}>
                    <img src={p.url} alt="" />
                    <button
                      type="button"
                      className="icon-btn sm"
                      onClick={() => removePhoto.mutate(p.id)}
                      aria-label={t("common.delete")}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
                {photos.length < MAX_PHOTOS && (
                  <button type="button" className="photo-add" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
                    <ImagePlus size={20} />
                    {upload.isPending ? t("employee.uploading") : t("employee.uploadPhoto")}
                  </button>
                )}
              </div>
              {!photos.length && <div className="muted text-sm">{t("employee.noPhotos")}</div>}
              <input
                ref={fileRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) upload.mutate(file);
                  e.target.value = "";
                }}
              />
            </>
          ) : (
            <div className="muted text-sm">{t("employee.photosAfterSave")}</div>
          )}
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
      </form>
    </Modal>
  );
}
