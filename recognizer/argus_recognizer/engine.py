"""Face detection (SCRFD) and embedding (ArcFace) on onnxruntime.

These are the same networks InsightFace's FaceAnalysis runs, called
directly, so the service needs no compiled extensions and runs on Linux
(CUDA), Windows (DirectML) or plain CPU.
"""

import io
import logging
import threading
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from argus_recognizer.config import Config
from argus_recognizer.models import ensure_models
from argus_recognizer.tracker import Face

log = logging.getLogger(__name__)

# Reference landmark positions in a 112x112 ArcFace crop: eyes, nose, mouth corners.
ARCFACE_DST = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]],
    dtype=np.float32,
)


def _session(path: Path, wanted: list[str]) -> ort.InferenceSession:
    available = ort.get_available_providers()
    providers = [p for p in wanted if p in available] or ["CPUExecutionProvider"]
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    return ort.InferenceSession(str(path), sess_options=opts, providers=providers)


def _nms(dets: np.ndarray, thresh: float) -> list[int]:
    x1, y1, x2, y2, scores = dets.T
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1 + 1) * np.maximum(0.0, yy2 - yy1 + 1)
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(iou <= thresh)[0] + 1]
    return keep


class Detector:
    """SCRFD with 3 strides x 2 anchors and 5 landmarks (det_10g / det_500m)."""

    strides = (8, 16, 32)
    anchors = 2

    def __init__(self, path: Path, providers: list[str], size: int):
        self.session = _session(path, providers)
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        self.size = size
        self._centers: dict[tuple[int, int], np.ndarray] = {}

    def _anchor_centers(self, h: int, w: int, stride: int) -> np.ndarray:
        key = (stride, h * w)
        if key not in self._centers:
            grid = np.stack(np.mgrid[:h, :w][::-1], axis=-1).astype(np.float32)
            centers = (grid * stride).reshape(-1, 2)
            self._centers[key] = np.repeat(centers, self.anchors, axis=0)
        return self._centers[key]

    def detect(self, img: np.ndarray, threshold: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
        """Returns boxes (N, 5: x1 y1 x2 y2 score) and landmarks (N, 5, 2)."""
        size = self.size
        h, w = img.shape[:2]
        scale = min(size / h, size / w)
        nh, nw = int(h * scale), int(w * scale)
        canvas = np.zeros((size, size, 3), dtype=np.uint8)
        canvas[:nh, :nw] = cv2.resize(img, (nw, nh))
        blob = cv2.dnn.blobFromImage(canvas, 1.0 / 128, (size, size), (127.5, 127.5, 127.5), swapRB=True)
        outs = self.session.run(self.output_names, {self.input_name: blob})
        if outs[0].ndim == 3:  # some exports keep the batch axis
            outs = [o[0] for o in outs]

        n = len(self.strides)
        boxes, points, scores = [], [], []
        for i, stride in enumerate(self.strides):
            score = outs[i].reshape(-1)
            keep = np.where(score >= threshold)[0]
            if not keep.size:
                continue
            centers = self._anchor_centers(size // stride, size // stride, stride)[keep]
            dist = outs[i + n][keep] * stride
            kps = outs[i + 2 * n][keep] * stride
            boxes.append(np.hstack([centers - dist[:, :2], centers + dist[:, 2:]]))
            points.append(np.repeat(centers, 5, axis=0).reshape(-1, 5, 2) + kps.reshape(-1, 5, 2))
            scores.append(score[keep])
        if not scores:
            return np.zeros((0, 5), np.float32), np.zeros((0, 5, 2), np.float32)

        dets = np.hstack([np.vstack(boxes) / scale, np.concatenate(scores)[:, None]]).astype(np.float32)
        kpss = (np.vstack(points) / scale).astype(np.float32)
        keep = _nms(dets, 0.4)
        return dets[keep], kpss[keep]


class Embedder:
    """ArcFace: aligned 112x112 face -> 512-d embedding."""

    def __init__(self, path: Path, providers: list[str]):
        self.session = _session(path, providers)
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        self.batched = not isinstance(inp.shape[0], int) or inp.shape[0] != 1

    @staticmethod
    def align(img: np.ndarray, kps: np.ndarray) -> np.ndarray:
        matrix, _ = cv2.estimateAffinePartial2D(kps, ARCFACE_DST, method=cv2.LMEDS)
        return cv2.warpAffine(img, matrix, (112, 112), borderValue=0.0)

    def embed(self, crops: list[np.ndarray]) -> np.ndarray:
        if not crops:
            return np.zeros((0, 512), np.float32)
        blob = cv2.dnn.blobFromImages(crops, 1.0 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
        if self.batched:
            out = self.session.run(None, {self.input_name: blob})[0]
        else:
            out = np.vstack([self.session.run(None, {self.input_name: b[None]})[0] for b in blob])
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return (out / np.maximum(norms, 1e-6)).astype(np.float32)


class FaceEngine:
    """Shared by all cameras. Calls are serialized: the GPU is the bottleneck anyway."""

    def __init__(self, cfg: Config):
        det_path, rec_path = ensure_models(cfg.models_dir, cfg.model_name)
        self.detector = Detector(det_path, cfg.providers, cfg.det_size)
        self.embedder = Embedder(rec_path, cfg.providers)
        self._lock = threading.Lock()
        log.info(
            "face models %s loaded, providers: %s",
            cfg.model_name,
            self.detector.session.get_providers(),
        )

    def detect(self, frame_bgr: np.ndarray, threshold: float = 0.5) -> list[Face]:
        with self._lock:
            dets, kpss = self.detector.detect(frame_bgr, threshold)
            crops = [Embedder.align(frame_bgr, k) for k in kpss]
            embeddings = self.embedder.embed(crops)
        return [
            Face(bbox=d[:4].copy(), det_score=float(d[4]), embedding=e)
            for d, e in zip(dets, embeddings)
        ]


class PhotoRejected(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# An employee photo is held to a higher bar than a live frame: it becomes
# the reference every later match is compared against.
PHOTO_MIN_FACE = 80
PHOTO_MIN_SCORE = 0.7


def decode_photo(data: bytes) -> np.ndarray:
    from PIL import Image, ImageOps

    try:
        img = Image.open(io.BytesIO(data))
        # Phone photos are often stored sideways with an EXIF rotation flag.
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise PhotoRejected("face_bad_image") from exc
    # Very large photos only slow detection down.
    img.thumbnail((1600, 1600))
    rgb = np.asarray(img)
    return np.ascontiguousarray(rgb[:, :, ::-1])


def embed_photo(engine: FaceEngine, data: bytes) -> np.ndarray:
    frame = decode_photo(data)
    faces = engine.detect(frame)
    if not faces:
        raise PhotoRejected("face_not_found")
    faces.sort(key=lambda f: f.size, reverse=True)
    # A small face in the background is fine; two faces of similar size are not.
    if len(faces) > 1 and faces[1].size >= faces[0].size * 0.5:
        raise PhotoRejected("face_multiple")
    face = faces[0]
    if face.size < PHOTO_MIN_FACE or face.det_score < PHOTO_MIN_SCORE:
        raise PhotoRejected("face_low_quality")
    return face.embedding
