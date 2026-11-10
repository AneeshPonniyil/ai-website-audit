from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .audit import audit_graph
from .fetch import FetchError, validate_url

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
app = FastAPI(title="AI Website Audit Assistant")


class AuditRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/audit")
async def audit(request: AuditRequest):
    try:
        url = str(validate_url(request.url.strip()))
    except FetchError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        result = await audit_graph.ainvoke({"url": url})
    except FetchError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result["report"]


if (ROOT / "frontend/dist/index.html").is_file():
    app.mount("/", StaticFiles(directory=ROOT / "frontend/dist", html=True), name="frontend")
