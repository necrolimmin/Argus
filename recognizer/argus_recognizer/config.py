import os
from dataclasses import dataclass, field
from pathlib import Path


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class Config:
    backend_url: str = os.environ.get("ARGUS_BACKEND_URL", "http://backend:8000")
    service_token: str = os.environ.get("ARGUS_SERVICE_TOKEN", "change-me-too")

    # InsightFace model pack: buffalo_l (accurate) or buffalo_s (lighter).
    model_name: str = os.environ.get("ARGUS_MODEL", "buffalo_l")
    models_dir: Path = Path(os.environ.get("ARGUS_MODELS_DIR", Path.home() / ".insightface" / "models"))
    det_size: int = int(_f("ARGUS_DET_SIZE", 640))
    # First available wins: CUDA on the Linux server, DirectML on Windows.
    providers: list[str] = field(
        default_factory=lambda: os.environ.get(
            "ARGUS_PROVIDERS", "CUDAExecutionProvider,DmlExecutionProvider,CPUExecutionProvider"
        ).split(",")
    )

    # Economy mode: sample rarely while the scene is empty, faster once a
    # face shows up, and stay fast for `active_hold` seconds after the last one.
    idle_fps: float = _f("ARGUS_IDLE_FPS", 1)
    active_fps: float = _f("ARGUS_ACTIVE_FPS", 5)
    active_hold: float = _f("ARGUS_ACTIVE_HOLD", 3)

    min_det_score: float = _f("ARGUS_MIN_DET_SCORE", 0.6)
    # Smallest face side (px) worth matching, and worth reporting as unknown.
    min_face: int = int(_f("ARGUS_MIN_FACE", 40))
    unknown_min_face: int = int(_f("ARGUS_UNKNOWN_MIN_FACE", 60))
    # A face that left the frame this long ago closes its track.
    track_ttl: float = _f("ARGUS_TRACK_TTL", 1.5)
    # An unrecognized face still in frame after this long is reported anyway.
    unknown_max_wait: float = _f("ARGUS_UNKNOWN_MAX_WAIT", 8)

    config_poll: float = _f("ARGUS_CONFIG_POLL", 15)


config = Config()
