from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from embeddings import get_embeddings
from generate import evaluate_transcript
from ingest import add_requirements
from requirements_store import init_requirements_table, list_requirements
from retrieve import deactivate_rule, search_requirements
from config import CORS_ORIGINS


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_embeddings()
    init_requirements_table()
    yield


app = FastAPI(
    title="saas-voice-rag",
    description="RAG API for checklist-based call quality evaluation",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


class RequirementIn(BaseModel):
    id: str | None = None
    scope: Literal["base", "client"] | None = None
    title: str = ""
    text: str = Field(min_length=1)
    client_id: str = ""
    category: str = ""


class IngestRequest(BaseModel):
    items: list[RequirementIn] = Field(min_length=1)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    client_id: str = ""
    k: int = Field(default=5, ge=1, le=50)


class EvaluateRequest(BaseModel):
    transcript: str = Field(min_length=1)
    client_id: str = ""
    score_scale: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/requirements")
def requirements(client_id: str = ""):
    try:
        return {"items": list_requirements(client_id=client_id)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Requirements database unavailable") from exc


@app.post("/requirements")
def ingest(req: IngestRequest):
    try:
        saved = add_requirements([item.model_dump(exclude_none=True) for item in req.items])
        return {"added": len(saved), "items": saved}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Requirement storage unavailable") from exc


@app.delete("/requirements/{requirement_id}")
def delete_requirement(requirement_id: str):
    if not deactivate_rule(requirement_id):
        raise HTTPException(status_code=404, detail="Requirement not found or already inactive")
    return {"id": requirement_id, "active": False}


@app.post("/search")
def search(req: SearchRequest):
    try:
        return {"results": search_requirements(req.query, client_id=req.client_id, k=req.k)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Vector search unavailable") from exc


@app.post("/evaluate")
def evaluate(req: EvaluateRequest):
    try:
        return evaluate_transcript(req.transcript, client_id=req.client_id, score_scale=req.score_scale)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Evaluation provider failed") from exc
