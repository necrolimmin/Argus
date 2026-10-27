import base64
import threading

import numpy as np


class Gallery:
    """Embeddings of all active employees, matched by cosine similarity.

    Every photo is a separate row, and an employee's score is their best
    photo. A few thousand rows fit easily in memory and match in microseconds.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._matrix = np.zeros((0, 512), dtype=np.float32)
        self._ids: list[str] = []
        self.version = ""

    def load(self, employees: list[dict], version: str) -> None:
        rows, ids = [], []
        for emp in employees:
            for raw in emp["embeddings"]:
                vec = np.frombuffer(base64.b64decode(raw), dtype=np.float32)
                norm = np.linalg.norm(vec)
                if norm > 0:
                    rows.append(vec / norm)
                    ids.append(emp["id"])
        matrix = np.stack(rows) if rows else np.zeros((0, 512), dtype=np.float32)
        with self._lock:
            self._matrix, self._ids, self.version = matrix, ids, version

    def match(self, embedding: np.ndarray) -> tuple[str | None, float]:
        with self._lock:
            matrix, ids = self._matrix, self._ids
        if not ids or matrix.shape[1] != embedding.shape[0]:
            return None, 0.0
        scores = matrix @ (embedding / (np.linalg.norm(embedding) or 1.0))
        best = int(np.argmax(scores))
        return ids[best], float(scores[best])

    def __len__(self) -> int:
        return len(self._ids)
