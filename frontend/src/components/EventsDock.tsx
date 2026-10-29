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

function time(iso: string) {
  return new Date(iso).toLocaleTimeString(intlLocale(), { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

interface Props {
  cameraIds: string[];
  defaultUnitId: string | null;
}

/** "Recognized" and "Unrecognized" panels under the camera wall. */
export function EventsDock({ cameraIds, defaultUnitId }: Props) {
  const { t } = useTranslation();
  const admin = isAdmin(useAuth((s) => s.user));
  const { feeds, connected, freshIds, loadMore, markLinked } = useLiveEvents(cameraIds);
  const [collapsed, setCollapsed] = useState(false);
  const [zoom, setZoom] = useState<string | null>(null);
  const [adding, setAdding] = useState<FaceEvent | null>(null);

  if (collapsed) {
    return (
      <section className="dock collapsed">
        <div className="dock-head grow">
          <span className={`live-dot${connected ? "" : " off"}`} />
          <h2>{t("events.recognized")}</h2>
          <span className="count">{feeds.recognized.items.length}</span>
          <h2 className="ml-3">{t("events.unknown")}</h2>
          <span className="count">{feeds.unknown.items.length}</span>
          <span className="spacer" />
          <button className="btn btn-ghost btn-sm" onClick={() => setCollapsed(false)}>
            <ChevronUp size={15} />
            {t("events.show")}
          </button>
        </div>
      </section>
    );
  }

  const column = (kind: EventKind) => {
    const feed = feeds[kind];
    return (
      <div className="dock-col" aria-live="polite">
        <div className="dock-head">
          <span
            className={`live-dot${connected ? "" : " off"}`}
            title={connected ? t("events.live") : t("events.reconnecting")}
          />
          <h2>{t(`events.${kind}`)}</h2>
          <span className="count">{feed.items.length}</span>
          <span className="spacer" />
          {kind === "unknown" && (
            <button className="icon-btn sm" onClick={() => setCollapsed(true)} aria-label={t("events.hide")} title={t("events.hide")}>
              <ChevronDown size={16} />
            </button>
          )}
        </div>
        <div className="dock-list">
          {!feed.loading && feed.items.length === 0 && (
            <div className="dock-empty">{t(kind === "recognized" ? "events.noRecognized" : "events.noUnknown")}</div>
          )}
          {feed.items.map((e) =>
            kind === "recognized" ? (
              <div key={e.id} className={`event${freshIds.has(e.id) ? " fresh" : ""}`}>
                <img className="event-face" src={e.image_url} alt="" loading="lazy" />
                <div className="event-main">
                  <div className="event-name">{e.employee?.full_name ?? "—"}</div>
                  <div className="event-sub">{[e.employee?.position, e.employee?.org_unit].filter(Boolean).join(", ")}</div>
                  <div className="event-sub">{e.camera_name}</div>
                </div>
                <div className="event-side">
                  <span className="event-time">{time(e.occurred_at)}</span>
                  <DirectionBadge direction={e.direction} />
                </div>
              </div>
            ) : (
              <div key={e.id} className={`event${freshIds.has(e.id) ? " fresh" : ""}`}>
                <button className="event-shot" onClick={() => setZoom(e.image_url)} aria-label={t("events.notRecognized")}>
                  <img src={e.image_url} alt="" loading="lazy" />
                </button>
                <div className="event-main">
                  <div className="event-name">{t("events.notRecognized")}</div>
                  <div className="event-sub">{e.camera_name}</div>
                  {e.linked_employee_name ? (
                    <div className="event-sub">{t("events.linked", { name: e.linked_employee_name })}</div>
                  ) : (
                    admin &&
                    e.face_url && (
                      <button className="btn btn-ghost btn-sm event-add" onClick={() => setAdding(e)}>
                        <UserPlus size={14} />
                        {t("events.addAsEmployee")}
                      </button>
                    )
                  )}
                </div>
                <div className="event-side">
                  <span className="event-time">{time(e.occurred_at)}</span>
                  <DirectionBadge direction={e.direction} />
                </div>
              </div>
            ),
          )}
          {feed.hasMore && (
            <button className="btn btn-ghost btn-sm more" onClick={() => loadMore(kind)} disabled={feed.loading}>
              {t("common.loadMore")}
            </button>
          )}
        </div>
      </div>
    );
  };

  return (
    <section className="dock">
      {column("recognized")}
      {column("unknown")}
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
