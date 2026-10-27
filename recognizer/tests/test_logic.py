from datetime import datetime

import numpy as np

from argus_recognizer.config import Config
from argus_recognizer.schedule import is_scheduled
from argus_recognizer.tracker import CameraTracker, Face

CFG = Config()
WORKDAY = [{"days": [1, 2, 3, 4, 5], "start": "07:00", "end": "20:00"}]
NIGHT = [{"days": [5], "start": "20:00", "end": "06:00"}]


def test_schedule_windows():
    monday = datetime(2026, 10, 19, 8, 0)
    assert is_scheduled([], monday)
    assert is_scheduled(WORKDAY, monday)
    assert not is_scheduled(WORKDAY, monday.replace(hour=20))
    assert not is_scheduled(WORKDAY, datetime(2026, 10, 24, 9, 0))  # Saturday
    # Friday night runs into Saturday morning.
    assert is_scheduled(NIGHT, datetime(2026, 10, 23, 22, 0))
    assert is_scheduled(NIGHT, datetime(2026, 10, 24, 5, 59))
    assert not is_scheduled(NIGHT, datetime(2026, 10, 24, 6, 0))


def _vec(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=512).astype(np.float32)
    return v / np.linalg.norm(v)


def _face(x: float, seed: int, size: float = 120) -> Face:
    return Face(bbox=np.array([x, 100, x + size, 100 + size], np.float32), det_score=0.9, embedding=_vec(seed))


FRAME = np.zeros((480, 640, 3), np.uint8)
known = _vec(1)


def match(emb):
    return ("emp-1", float(emb @ known))


def test_recognized_is_deduplicated():
    t = CameraTracker(CFG, dedup_seconds=60, match_threshold=0.45)
    events = []
    for i in range(30):  # ten seconds at 3 fps
        events += t.update([_face(100 + i, 1)], FRAME, 1000 + i / 3, match)
    assert [e.kind for e in events] == ["recognized"]
    later = t.update([_face(100, 1)], FRAME, 1061, match)
    assert [e.kind for e in later] == ["recognized"]


def test_unknown_reported_once_when_face_leaves():
    t = CameraTracker(CFG, dedup_seconds=60, match_threshold=0.45)
    events = []
    for i in range(6):
        size = 80 + i * 10  # walking towards the camera
        events += t.update([_face(200, 7, size)], FRAME, 1000 + i * 0.2, match)
    assert events == []
    events += t.update([], FRAME, 1003, match)
    assert [e.kind for e in events] == ["unknown"]
    assert events[0].face.size == 130  # the best (largest) frame

    # The same stranger coming back within the dedup window is not repeated.
    for i in range(3):
        events += t.update([_face(200, 7)], FRAME, 1010 + i * 0.2, match)
    events += t.update([], FRAME, 1013, match)
    assert len(events) == 1


def test_single_frame_and_tiny_faces_are_ignored():
    t = CameraTracker(CFG, dedup_seconds=60, match_threshold=0.45)
    events = t.update([_face(50, 9)], FRAME, 1000, match)
    events += t.update([], FRAME, 1005, match)
    for i in range(5):
        events += t.update([_face(300, 11, size=30)], FRAME, 1010 + i * 0.2, match)
    events += t.update([], FRAME, 1015, match)
    assert events == []
