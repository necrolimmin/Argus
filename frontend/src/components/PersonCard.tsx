import { useQuery } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import type { FaceEvent } from "../api/types";
import { intlLocale } from "../i18n";
import { isAdmin, useAuth } from "../lib/store";
import { DirectionBadge } from "./DirectionBadge";
import { EmployeeModal } from "./EmployeeModal";
import { Modal } from "./Modal";
import { Thumb } from "./NoImage";

interface Props {
  event: FaceEvent;
  /** The recognized events already on screen; this person's other passes are picked from them. */
  recent: FaceEvent[];
  onClose: () => void;
}

/**
 * Who was recognized: what was entered about the employee, the pass that
 * was clicked, and the same person's other passes among the events shown.
 */
export function PersonCard({ event, recent, onClose }: Props) {
  const { t } = useTranslation();
  const admin = isAdmin(useAuth((s) => s.user));
  const [zoom, setZoom] = useState(false);
  const [editing, setEditing] = useState(false);
  const person = event.employee;
  // A viewer may not read the staff list; then the card shows what the event itself carries.
  const details = useQuery({
    queryKey: ["employee", person?.id],
    queryFn: () => api.employee(person!.id),
    enabled: !!person,
    retry: false,
  });
  if (!person) return null;
  const emp = details.data;
  const locale = intlLocale();
  const at = new Date(event.occurred_at);
  const passes = recent.filter((e) => e.employee?.id === person.id);
  const clock = (iso: string) => new Date(iso).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  if (editing && emp) {
    return (
      <EmployeeModal
        employee={emp}
        onSaved={() => details.refetch()}
        onClose={() => {
          setEditing(false);
          details.refetch();
        }}
      />
    );
  }

  return (
    <Modal
      title={t("events.person")}
      onClose={onClose}
      footer={
        <>
          {admin && emp && (
            <button className="btn" onClick={() => setEditing(true)}>
              <Pencil size={15} aria-hidden />
              {t("common.edit")}
            </button>
          )}
          <button className="btn btn-primary" onClick={onClose}>
            {t("common.close")}
          </button>
        </>
      }
    >
      <div className="person-card">
        <div className="person-photo">
          <Thumb src={emp?.photos[0]?.url || event.face_url || event.image_url} />
        </div>
        <div className="person-main">
          <h3 className="person-name">{emp?.full_name ?? person.full_name}</h3>
          <p className="person-position">{(emp?.position ?? person.position) || "—"}</p>
          <dl className="person-facts">
            <dt>{t("employee.unit")}</dt>
            <dd>{person.org_unit || "—"}</dd>
            {emp && (
              <>
                <dt>{t("employee.personnelNumber")}</dt>
                <dd className="num">{emp.personnel_number || "—"}</dd>
                <dt>{t("employee.phone")}</dt>
                <dd className="num">{emp.phone ? <a href={`tel:${emp.phone}`}>{emp.phone}</a> : "—"}</dd>
                <dt>{t("org.status")}</dt>
                <dd>
                  <span className={`status${emp.is_active ? "" : " off"}`}>{emp.is_active ? t("common.active") : t("common.inactive")}</span>
                </dd>
              </>
            )}
          </dl>
        </div>
      </div>

      <section className="person-pass" aria-label={t("events.thisPass")}>
        <h3>{t("events.thisPass")}</h3>
        <div className="pass-body">
          <button type="button" className="pass-shot" onClick={() => setZoom(true)} aria-label={t("events.frameShot")} title={t("events.frameShot")}>
            <Thumb src={event.image_url} compact />
          </button>
          <dl className="person-facts">
            <dt>{t("events.passTime")}</dt>
            <dd className="num">
              {at.toLocaleDateString(locale, { day: "numeric", month: "long" })}, {clock(event.occurred_at)}
            </dd>
            <dt>{t("events.camera")}</dt>
            <dd>{event.camera_name || "—"}</dd>
            {event.direction !== "none" && (
              <>
                <dt>{t("events.direction")}</dt>
                <dd>
                  <DirectionBadge direction={event.direction} />
                </dd>
              </>
            )}
            {event.similarity !== null && (
              <>
                <dt>{t("events.similarity")}</dt>
                <dd className="num">{Math.round(event.similarity * 100)}%</dd>
              </>
            )}
          </dl>
        </div>
      </section>

      {passes.length > 1 && (
        <section className="person-pass" aria-label={t("events.passes")}>
          <h3>
            {t("events.passes")} <span className="num muted">{passes.length}</span>
          </h3>
          <ul className="pass-list">
            {passes.map((e) => (
              <li key={e.id} className={e.id === event.id ? "current" : undefined}>
                <span className="num">{clock(e.occurred_at)}</span>
                <DirectionBadge direction={e.direction} />
                <span className="muted">{e.camera_name}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {zoom &&
        createPortal(
          <div className="lightbox person-zoom" onClick={() => setZoom(false)} role="dialog">
            <img src={event.image_url} alt="" />
          </div>,
          document.body,
        )}
    </Modal>
  );
}
