from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.security import verify_media
from app.services.media import media_root

router = APIRouter(tags=["media"])


@router.get("/media/{path:path}")
async def get_media(path: str, exp: int, sig: str):
    if not verify_media(path, exp, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bad_media_link")
    root = media_root().resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    # Files never change once written, so the browser may keep them.
    return FileResponse(target, headers={"Cache-Control": "private, max-age=21600, immutable"})
