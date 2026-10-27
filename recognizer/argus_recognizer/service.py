"""Keeps one reader per scheduled camera and turns frames into events."""

import base64
import logging
import queue
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import cv2
import httpx
import numpy as np

from argus_recognizer.config import Config
from argus_recognizer.engine import FaceEngine
from argus_recognizer.gallery import Gallery
from argus_recognizer.schedule import is_scheduled
from argus_recognizer.stream import CameraReader
from argus_recognizer.tracker import CameraTracker, Event, Face

log = logging.getLogger(__name__)


def _jpeg(image: np.ndarray, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("jpeg encode failed")
    return buf.tobytes()


# Unknown-face screenshots are stored for 60 days; a 4K frame would be
# ~1 MB each, so they are scaled down to this width first.
SCREENSHOT_MAX_WIDTH = 1280


def _screenshot(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= SCREENSHOT_MAX_WIDTH:
        return frame
    scale = SCREENSHOT_MAX_WIDTH / w
    return cv2.resize(frame, (SCREENSHOT_MAX_WIDTH, int(h * scale)), interpolation=cv2.INTER_AREA)


def face_crop(frame: np.ndarray, face: Face, margin: float = 0.4) -> np.ndarray:
    x1, y1, x2, y2 = face.bbox
    w, h = x2 - x1, y2 - y1
    x1, x2 = int(max(0, x1 - w * margin)), int(min(frame.shape[1], x2 + w * margin))
    y1, y2 = int(max(0, y1 - h * margin)), int(min(frame.shape[0], y2 + h * margin))
    return frame[y1:y2, x1:x2]


class Recognizer:
    def __init__(self, cfg: Config, engine: FaceEngine):
        self.cfg = cfg
        self.engine = engine
        self.gallery = Gallery()
        self.http = httpx.Client(
            base_url=cfg.backend_url, headers={"X-Service-Token": cfg.service_token}, timeout=15
        )
        self.cameras: dict[str, dict] = {}
        self.readers: dict[str, CameraReader] = {}
        self.trackers: dict[str, CameraTracker] = {}
        self.active_until: dict[str, float] = {}
        self.settings = {"dedup_seconds": 60, "match_threshold": 0.45, "timezone": "UTC"}
        self._wake = threading.Event()
        self._outbox: queue.Queue[tuple[str, Event]] = queue.Queue(maxsize=1000)

    # --- lifecycle --------------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=self._config_loop, name="config", daemon=True).start()
        threading.Thread(target=self._infer_loop, name="infer", daemon=True).start()
        threading.Thread(target=self._send_loop, name="sender", daemon=True).start()

    def status(self) -> dict:
        return {
            "cameras": len(self.cameras),
            "running": len(self.readers),
            "connected": sum(r.connected for r in self.readers.values()),
            "gallery": len(self.gallery),
        }

    # --- config & schedule ------------------------------------------------

    def _config_loop(self) -> None:
        while True:
            try:
                self._refresh()
            except Exception as exc:  # noqa: BLE001
                log.warning("config refresh failed: %s", exc)
            time.sleep(self.cfg.config_poll)

    def _refresh(self) -> None:
        data = self.http.get("/api/internal/recognizer/config").raise_for_status().json()
        self.settings = {k: data[k] for k in ("dedup_seconds", "match_threshold", "timezone")}
        if data["gallery_version"] != self.gallery.version:
            g = self.http.get("/api/internal/recognizer/gallery").raise_for_status().json()
            self.gallery.load(g["employees"], g["version"])
            log.info("gallery loaded: %d embeddings", len(self.gallery))

        self.cameras = {c["id"]: c for c in data["cameras"]}
        now_local = datetime.now(ZoneInfo(self.settings["timezone"]))
        wanted = {cid for cid, c in self.cameras.items() if is_scheduled(c["schedule"], now_local)}

        for cid in list(self.readers):
            changed = cid in self.cameras and self.cameras[cid]["stream_url"] != self.readers[cid].url
            if cid not in wanted or changed:
                self._stop_camera(cid)
        for cid in wanted - self.readers.keys():
            reader = CameraReader(cid, self.cameras[cid]["stream_url"], self._wake)
            reader.fps = self.cfg.idle_fps
            self.readers[cid] = reader
            reader.start()
        for tracker in self.trackers.values():
            tracker.dedup_seconds = self.settings["dedup_seconds"]
            tracker.match_threshold = self.settings["match_threshold"]

    def _stop_camera(self, cid: str) -> None:
        self.readers.pop(cid).stop()
        tracker = self.trackers.pop(cid, None)
        if tracker:
            for event in tracker.flush(time.time()):
                self._queue(cid, event)

    # --- inference --------------------------------------------------------

    def _tracker(self, cid: str) -> CameraTracker:
        if cid not in self.trackers:
            self.trackers[cid] = CameraTracker(
                self.cfg,
                dedup_seconds=self.settings["dedup_seconds"],
                match_threshold=self.settings["match_threshold"],
            )
        return self.trackers[cid]

    def _infer_loop(self) -> None:
        while True:
            self._wake.wait(1.0)
            self._wake.clear()
            # Round-robin: every camera with a due frame gets one pass.
            for cid, reader in list(self.readers.items()):
                item = reader.take()
                if item is None:
                    continue
                frame, at = item
                try:
                    faces = self.engine.detect(frame)
                except Exception as exc:  # noqa: BLE001
                    log.warning("inference failed on %s: %s", cid, exc)
                    continue
                tracker = self._tracker(cid)
                for event in tracker.update(faces, frame, at, self.gallery.match):
                    self._queue(cid, event)
                self._set_mode(cid, reader, bool(faces) or tracker.has_faces, at)

    def _set_mode(self, cid: str, reader: CameraReader, busy: bool, at: float) -> None:
        if busy:
            self.active_until[cid] = at + self.cfg.active_hold
        active = self.active_until.get(cid, 0) > time.time()
        reader.fps = self.cfg.active_fps if active else self.cfg.idle_fps

    # --- delivery ---------------------------------------------------------

    def _queue(self, cid: str, event: Event) -> None:
        try:
            self._outbox.put_nowait((cid, event))
        except queue.Full:
            log.warning("outbox full, dropping event from %s", cid)

    def _send_loop(self) -> None:
        while True:
            cid, event = self._outbox.get()
            for attempt in range(5):
                try:
                    self._post(cid, event)
                    break
                except Exception as exc:  # noqa: BLE001
                    log.warning("event post failed (%d): %s", attempt + 1, exc)
                    time.sleep(2**attempt)

    def _post(self, cid: str, event: Event) -> None:
        crop = _jpeg(face_crop(event.frame, event.face))
        data = {
            "camera_id": cid,
            "kind": event.kind,
            "occurred_at": datetime.fromtimestamp(event.at, timezone.utc).isoformat(),
        }
        if event.kind == "recognized":
            data["employee_id"] = event.employee_id
            data["similarity"] = f"{event.similarity:.4f}"
            files = {"image": ("face.jpg", crop, "image/jpeg")}
        else:
            # The screenshot is what operators see; the crop and embedding
            # let an admin turn this person into an employee.
            data["embedding"] = base64.b64encode(event.face.embedding.tobytes()).decode()
            files = {
                "image": ("frame.jpg", _jpeg(_screenshot(event.frame), 80), "image/jpeg"),
                "face": ("face.jpg", crop, "image/jpeg"),
            }
        r = self.http.post("/api/internal/events", data=data, files=files)
        if r.status_code in (404, 422):
            log.info("event dropped by backend: %s", r.text[:200])
            return
        r.raise_for_status()
