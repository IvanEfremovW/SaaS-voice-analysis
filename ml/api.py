from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from company_requirements import add_company_requirements
from config import CORS_ORIGINS
from generate import evaluate_transcript
from ingest import add_requirements
from requirements_store import init_requirements_table
from retrieve import deactivate_rule, get_rules_for_administrator, search_company_requirements


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    scope: Literal["base", "administrator", "client"] | None = None
    title: str = ""
    text: str = Field(min_length=1)
    administrator_id: str = ""
    client_id: str = ""  # Legacy alias for administrator_id.
    category: str = ""


class IngestRequest(BaseModel):
    items: list[RequirementIn] = Field(min_length=1)


class CompanyRequirementIn(BaseModel):
    id: str | None = None
    title: str = ""
    text: str = Field(min_length=1)
    category: str = ""


class CompanyRequirementsRequest(BaseModel):
    company_id: str = Field(min_length=1)
    items: list[CompanyRequirementIn] = Field(min_length=1)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=50)


class EvaluateRequest(BaseModel):
    transcript: str = Field(min_length=1)
    administrator_id: str = ""
    company_id: str = ""
    client_id: str = Field(default="", max_length=0, description="Use administrator_id and company_id instead")
    score_scale: str | None = None
    retrieval_k: int = Field(default=10, ge=1, le=50)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/requirements")
def requirements(administrator_id: str = ""):
    try:
        return {"items": get_rules_for_administrator(administrator_id=administrator_id)}
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
    try:
        deactivated = deactivate_rule(requirement_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Requirement storage unavailable") from exc
    if not deactivated:
        raise HTTPException(status_code=404, detail="Requirement not found or already inactive")
    return {"id": requirement_id, "active": False}


@app.post("/company-requirements")
def ingest_company_requirements(req: CompanyRequirementsRequest):
    try:
        saved = add_company_requirements(
            req.company_id, [item.model_dump(exclude_none=True) for item in req.items]
        )
        return {"added": len(saved), "items": saved}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Company requirement vector storage unavailable") from exc


@app.post("/search")
def search(req: SearchRequest):
    try:
        return {"results": search_company_requirements(req.query, company_id=req.company_id, k=req.k)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Company requirement vector search unavailable") from exc


@app.post("/evaluate")
def evaluate(req: EvaluateRequest):
    try:
        return evaluate_transcript(
            req.transcript,
            administrator_id=req.administrator_id,
            company_id=req.company_id,
            score_scale=req.score_scale,
            retrieval_k=req.retrieval_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Evaluation provider failed") from exc
