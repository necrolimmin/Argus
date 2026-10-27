"""Turns per-frame face detections into events, one per person.

A person standing in front of the camera is detected on every sampled
frame. This module groups those detections into tracks and decides when to
report:

* recognized: as soon as a match is found, then at most once per
  `dedup_seconds` for the same employee on this camera;
* unknown: once per track, when the face leaves the frame (or after
  `unknown_max_wait`), with the best-quality frame seen, and only if the
  track was never recognized and no similar unknown was reported recently.
"""

from dataclasses import dataclass, field

import numpy as np

from argus_recognizer.config import Config


@dataclass
class Face:
    bbox: np.ndarray  # x1, y1, x2, y2
    det_score: float
    embedding: np.ndarray

    @property
    def size(self) -> float:
        w, h = self.bbox[2] - self.bbox[0], self.bbox[3] - self.bbox[1]
        return float(min(w, h))

    @property
    def quality(self) -> float:
        return self.det_score * self.size


@dataclass
class Track:
    bbox: np.ndarray
    started: float
    last_seen: float
    hits: int = 1
    recognized: bool = False
    reported: bool = False
    best_quality: float = -1.0
    best_face: Face | None = None
    best_frame: np.ndarray | None = None
    best_at: float = 0.0


@dataclass
class Event:
    kind: str  # "recognized" | "unknown"
    at: float
    frame: np.ndarray
    face: Face
    employee_id: str | None = None
    similarity: float | None = None


def iou(a: np.ndarray, b: np.ndarray) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / union) if union > 0 else 0.0


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) or 1.0)


@dataclass
class CameraTracker:
    cfg: Config
    dedup_seconds: float = 60
    match_threshold: float = 0.45
    tracks: list[Track] = field(default_factory=list)
    last_recognized: dict[str, float] = field(default_factory=dict)
    recent_unknown: list[tuple[float, np.ndarray]] = field(default_factory=list)

    def update(self, faces: list[Face], frame: np.ndarray, now: float, match) -> list[Event]:
        """`match(embedding) -> (employee_id | None, similarity)`."""
        events: list[Event] = []
        faces = [f for f in faces if f.det_score >= self.cfg.min_det_score and f.size >= self.cfg.min_face]

        for face in faces:
            track = self._assign(face, now)
            if face.quality > track.best_quality:
                track.best_quality, track.best_face, track.best_frame = face.quality, face, frame
                track.best_at = now

            employee_id, similarity = match(face.embedding)
            if employee_id is None or similarity < self.match_threshold:
                continue
            track.recognized = True
            last = self.last_recognized.get(employee_id)
            if last is None or now - last >= self.dedup_seconds:
                self.last_recognized[employee_id] = now
                events.append(Event("recognized", now, frame, face, employee_id, similarity))

        events.extend(self._close_tracks(now))
        return events

    def flush(self, now: float) -> list[Event]:
        """Closes every track, e.g. when the camera stops for its schedule."""
        events = self._close_tracks(now + self.cfg.track_ttl + 1)
        self.tracks.clear()
        return events

    @property
    def has_faces(self) -> bool:
        return bool(self.tracks)

    def _assign(self, face: Face, now: float) -> Track:
        best, best_iou = None, 0.3
        for t in self.tracks:
            score = iou(t.bbox, face.bbox)
            if score > best_iou:
                best, best_iou = t, score
        if best is None:
            best = Track(bbox=face.bbox, started=now, last_seen=now)
            self.tracks.append(best)
        else:
            best.bbox, best.last_seen, best.hits = face.bbox, now, best.hits + 1
        return best

    def _close_tracks(self, now: float) -> list[Event]:
        events, alive = [], []
        for t in self.tracks:
            gone = now - t.last_seen > self.cfg.track_ttl
            overdue = now - t.started >= self.cfg.unknown_max_wait
            if (gone or overdue) and not t.reported:
                event = self._unknown_event(t, now)
                if event:
                    events.append(event)
                t.reported = t.reported or overdue
            if not gone:
                alive.append(t)
        self.tracks = alive
        return events

    def _unknown_event(self, t: Track, now: float) -> Event | None:
        # A single-frame detection is usually a false positive.
        if t.recognized or t.hits < 2 or t.best_face is None:
            return None
        if t.best_face.size < self.cfg.unknown_min_face:
            return None
        vec = _unit(t.best_face.embedding)
        self.recent_unknown = [(ts, v) for ts, v in self.recent_unknown if now - ts < self.dedup_seconds]
        if any(float(v @ vec) >= self.match_threshold for _, v in self.recent_unknown):
            return None
        self.recent_unknown.append((now, vec))
        t.reported = True
        return Event("unknown", t.best_at, t.best_frame, t.best_face)
