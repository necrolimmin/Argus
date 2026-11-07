import { ChevronDown, ChevronUp, UserPlus } from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import type { EventKind, FaceEvent } from "../api/types";
import { intlLocale } from "../i18n";
import { useLiveEvents } from "../lib/events";
import { isAdmin, useAuth } from "../lib/store";
import { DirectionBadge } from "./DirectionBadge";
import { EmployeeModal } from "./EmployeeModal";
import { Thumb } from "./NoImage";

function time(iso: string) {
  return new Date(iso).toLocaleTimeString(intlLocale(), { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

interface Props {
  cameraIds: string[];
  defaultUnitId: string | null;
}

/**
 * "Recognized" and "Unrecognized" under the camera wall, each a filmstrip of
 * frames read left to right from the newest, like the timeline of a
 * recorder. A lane with nothing today is one line, not an empty box.
 */
export function EventsDock({ cameraIds, defaultUnitId }: Props) {
  const { t } = useTranslation();
  const admin = isAdmin(useAuth((s) => s.user));
  const { feeds, connected, freshIds, loadMore, markLinked } = useLiveEvents(cameraIds);
  const [collapsed, setCollapsed] = useState(false);
  const [zoom, setZoom] = useState<string | null>(null);
  const [adding, setAdding] = useState<FaceEvent | null>(null);

  const isEmpty = (kind: EventKind) => !feeds[kind].loading && feeds[kind].items.length === 0;
  const quiet = isEmpty("recognized") && isEmpty("unknown");

  const head = (kind: EventKind) => (
    <div className="lane-head">
      <span className={`live-dot${connected ? "" : " off"}`} title={connected ? t("events.live") : t("events.reconnecting")} />
      <h2>{t(`events.${kind}`)}</h2>
      <span className="count">{feeds[kind].items.length}</span>
    </div>
  );

  if (collapsed) {
    return (
      <section className="dock collapsed">
        {head("recognized")}
        {head("unknown")}
        <span className="spacer" />
        <button className="btn btn-ghost btn-sm" onClick={() => setCollapsed(false)}>
          <ChevronUp size={15} />
          {t("events.show")}
        </button>
      </section>
    );
  }

  const lane = (kind: EventKind) => {
    const feed = feeds[kind];
    return (
      <div className={`lane${isEmpty(kind) ? " lane-quiet" : ""}`} aria-live="polite">
        {head(kind)}
        {isEmpty(kind) ? (
          <p className="lane-empty">{t(kind === "recognized" ? "events.noRecognized" : "events.noUnknown")}</p>
        ) : (
          <div className="strip">
            {feed.items.map((e) =>
              kind === "recognized" ? (
                <figure key={e.id} className={`frame person${freshIds.has(e.id) ? " fresh" : ""}`} data-direction={e.direction}>
                  <button className="frame-shot" onClick={() => setZoom(e.image_url)} aria-label={e.employee?.full_name ?? ""}>
                    <Thumb src={e.face_url || e.image_url} compact />
                  </button>
                  <figcaption>
                    <span className="frame-time num">{time(e.occurred_at)}</span>
                    <span className="frame-title">{e.employee?.full_name ?? "—"}</span>
                    <span className="frame-meta">
                      <DirectionBadge direction={e.direction} iconOnly />
                      {e.camera_name}
                    </span>
                  </figcaption>
                </figure>
              ) : (
                <figure key={e.id} className={`frame${freshIds.has(e.id) ? " fresh" : ""}`} data-direction={e.direction}>
                  <button className="frame-shot" onClick={() => setZoom(e.image_url)} aria-label={t("events.notRecognized")}>
                    <Thumb src={e.image_url} compact />
                  </button>
                  <figcaption>
                    <span className="frame-time num">{time(e.occurred_at)}</span>
                    <span className="frame-meta">
                      <DirectionBadge direction={e.direction} iconOnly />
                      {e.linked_employee_name ? t("events.linked", { name: e.linked_employee_name }) : e.camera_name}
                    </span>
                  </figcaption>
                  {admin && e.face_url && !e.linked_employee_name && (
                    <button
                      className="icon-btn sm frame-add"
                      onClick={() => setAdding(e)}
                      title={t("events.addAsEmployee")}
                      aria-label={t("events.addAsEmployee")}
                    >
                      <UserPlus size={15} />
                    </button>
                  )}
                </figure>
              ),
            )}
            {feed.hasMore && (
              <button className="btn btn-ghost btn-sm strip-more" onClick={() => loadMore(kind)} disabled={feed.loading}>
                {t("common.loadMore")}
              </button>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <section className={`dock${quiet ? " quiet" : ""}`}>
      {lane("recognized")}
      {lane("unknown")}
      <button className="icon-btn sm dock-hide" onClick={() => setCollapsed(true)} aria-label={t("events.hide")} title={t("events.hide")}>
        <ChevronDown size={16} />
      </button>
      {zoom &&
        createPortal(
          <div className="lightbox" onClick={() => setZoom(null)} role="dialog">
            <img src={zoom} alt="" />
          </div>,
          document.body,
        )}
      {adding && (
        <EmployeeModal
          fromEvent={adding}
          defaultUnitId={defaultUnitId}
          onSaved={(emp) => markLinked(adding.id, emp.full_name)}
          onClose={() => setAdding(null)}
        />
      )}
    </section>
  );
}
