"""Downloads the InsightFace model pack on first start.

Only two networks from the pack are used: the SCRFD face detector and the
ArcFace embedder. Everything else in the archive is skipped.
"""

import logging
import shutil
import tempfile
import zipfile
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

PACKS = {
    # name: (detector, embedder)
    "buffalo_l": ("det_10g.onnx", "w600k_r50.onnx"),
    "buffalo_s": ("det_500m.onnx", "w600k_mbf.onnx"),
}
URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/{name}.zip"


def ensure_models(root: Path, name: str) -> tuple[Path, Path]:
    if name not in PACKS:
        raise ValueError(f"unknown model pack {name!r}, expected one of {list(PACKS)}")
    folder = root / name
    files = [folder / f for f in PACKS[name]]
    if all(f.is_file() for f in files):
        return files[0], files[1]

    folder.mkdir(parents=True, exist_ok=True)
    url = URL.format(name=name)
    log.info("downloading face models from %s", url)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / f"{name}.zip"
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with archive.open("wb") as out:
                for chunk in r.iter_bytes(1 << 20):
                    out.write(chunk)
        with zipfile.ZipFile(archive) as z:
            for member in z.namelist():
                base = Path(member).name
                if base in PACKS[name]:
                    with z.open(member) as src, (folder / base).open("wb") as dst:
                        shutil.copyfileobj(src, dst)
    missing = [f.name for f in files if not f.is_file()]
    if missing:
        raise RuntimeError(f"model archive did not contain {missing}")
    log.info("face models ready in %s", folder)
    return files[0], files[1]
