import base64

import httpx

from app.config import get_settings


class RecognizerUnavailable(Exception):
    pass


class FaceCheckError(Exception):
    """The photo is not usable; `code` is shown to the user via i18n."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


async def embed_photo(image: bytes, filename: str) -> bytes:
    """Return the float32 embedding of the single face on the photo."""
    try:
        async with httpx.AsyncClient(base_url=get_settings().recognizer_url, timeout=30) as c:
            r = await c.post("/embed", files={"image": (filename, image)})
    except httpx.HTTPError as exc:
        raise RecognizerUnavailable() from exc
    if r.status_code == 422:
        raise FaceCheckError(r.json().get("detail", "face_bad_image"))
    if r.status_code >= 400:
        raise RecognizerUnavailable()
    return base64.b64decode(r.json()["embedding"])
