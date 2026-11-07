import { ChevronLeft, ChevronRight, Pause, Play, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import type { Camera } from "../api/types";
import { load, save } from "../lib/storage";
import { CameraTile } from "./CameraTile";

const STEPS = [10, 20, 30, 60];
const STEP_KEY = "argus.patrolSeconds";

/**
 * A guard's round: the chosen cameras one after another, full screen, each
 * for a few seconds. The thin bar under the name shows when the next one comes.
 */
export function Patrol({ cameras, startAt = 0, onClose }: { cameras: Camera[]; startAt?: number; onClose: () => void }) {
  const { t } = useTranslation();
  const [index, setIndex] = useState(startAt % cameras.length);
  const [paused, setPaused] = useState(false);
  const [seconds, setSeconds] = useState(() => load<number>(STEP_KEY, 20));
  // Bumped on every change of camera, so the countdown bar starts over.
  const [lap, setLap] = useState(0);

  const go = useCallback(
    (delta: number) => {
      setIndex((i) => (i + delta + cameras.length) % cameras.length);
      setLap((n) => n + 1);
    },
    [cameras.length],
  );

  // After a pause the camera gets its full time again, bar and timer alike.
  const toggle = useCallback(() => {
    if (paused) setLap((n) => n + 1);
    setPaused(!paused);
  }, [paused]);

  useEffect(() => {
    if (paused) return;
    const timer = window.setTimeout(() => go(1), seconds * 1000);
    return () => window.clearTimeout(timer);
  }, [paused, seconds, lap, go]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
      else if (e.key === " ") {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, onClose, toggle]);

  const camera = cameras[index];
  const next = cameras[(index + 1) % cameras.length];

  return createPortal(
    <div className="fullscreen patrol" role="dialog" aria-label={t("cameras.patrol")}>
      <div className="fill">
        <CameraTile key={camera.id} camera={camera} quality="main" />
      </div>

      <div className="patrol-bar">
        <div className="patrol-now">
          <span className="patrol-count num">
            {index + 1}
            <span>/{cameras.length}</span>
          </span>
          <span className="patrol-name">{camera.name}</span>
          {cameras.length > 1 && <span className="patrol-next">→ {next.name}</span>}
        </div>
        <div className="patrol-controls">
          <button className="icon-btn" onClick={() => go(-1)} aria-label={t("cameras.patrolPrev")} title={t("cameras.patrolPrev")}>
            <ChevronLeft size={18} />
          </button>
          <button
            className="icon-btn"
            onClick={toggle}
            aria-label={paused ? t("cameras.patrolPlay") : t("cameras.patrolPause")}
            title={paused ? t("cameras.patrolPlay") : t("cameras.patrolPause")}
          >
            {paused ? <Play size={18} /> : <Pause size={18} />}
          </button>
          <button className="icon-btn" onClick={() => go(1)} aria-label={t("cameras.patrolNext")} title={t("cameras.patrolNext")}>
            <ChevronRight size={18} />
          </button>
          <label className="patrol-step">
            <span>{t("cameras.patrolEvery")}</span>
            <select
              value={seconds}
              onChange={(e) => {
                const value = Number(e.target.value);
                setSeconds(value);
                save(STEP_KEY, value);
                setLap((n) => n + 1);
              }}
            >
              {STEPS.map((s) => (
                <option key={s} value={s}>
                  {t("cameras.patrolSeconds", { n: s })}
                </option>
              ))}
            </select>
          </label>
          <button className="icon-btn" onClick={onClose} aria-label={t("common.close")} title={t("common.close")}>
            <X size={18} />
          </button>
        </div>
        <span className="patrol-track" aria-hidden>
          <i
            key={lap}
            className={paused ? "paused" : undefined}
            style={{ animationDuration: `${seconds}s` }}
          />
        </span>
      </div>
    </div>,
    document.body,
  );
}
