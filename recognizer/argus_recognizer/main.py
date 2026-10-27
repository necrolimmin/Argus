import asyncio
import base64
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile

from argus_recognizer.config import config
from argus_recognizer.engine import FaceEngine, PhotoRejected, embed_photo
from argus_recognizer.service import Recognizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = FaceEngine(config)
    recognizer = Recognizer(config, engine)
    recognizer.start()
    state.update(engine=engine, recognizer=recognizer)
    yield


app = FastAPI(title="Argus recognizer", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", **state["recognizer"].status()}


@app.post("/embed")
async def embed(image: UploadFile):
    """Checks an employee photo and returns its face embedding."""
    data = await image.read()
    try:
        vec = await asyncio.to_thread(embed_photo, state["engine"], data)
    except PhotoRejected as exc:
        raise HTTPException(422, exc.code) from exc
    return {"embedding": base64.b64encode(vec.tobytes()).decode()}
