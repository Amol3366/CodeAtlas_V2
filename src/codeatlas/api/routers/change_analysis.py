"""Change-analysis routes: the four endpoints of `AGENTS.md` Section 12.4.

Thin, like every other router. Each handler validates its input, calls
`ChangeAnalysisService`, and serializes the result; no repository logic lives
here, so the CLI and MCP answer identically by construction.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from codeatlas.api.errors import request_id_for
from codeatlas.api.routers.repositories import Services
from codeatlas.application.change_analysis import ChangeAnalysisRequest
from codeatlas.contracts import ChangeAnalysisReport, ContractModel
from codeatlas.delivery import render_markdown, render_sarif

router = APIRouter(prefix="/v1/change-analysis", tags=["change-analysis"])

ReportFormat = Literal["json", "markdown", "sarif"]

_DEFAULT_FORMAT = Query(default="json")


class WorkingTreeRequest(ContractModel):
    """Analyze the working tree against a base ref."""

    repository_id: str
    base_ref: str = "HEAD"


class CommitRangeRequest(ContractModel):
    """Analyze one commit range."""

    repository_id: str
    base_ref: str
    target_ref: str = "HEAD"


@router.post("/working-tree")
def analyze_working_tree(
    request: Request, services: Services, body: WorkingTreeRequest
) -> ChangeAnalysisReport:
    return services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(
            repository_id=body.repository_id,
            base_ref=body.base_ref,
            request_id=request_id_for(request),
        )
    )


@router.post("/commits")
def analyze_commits(
    request: Request, services: Services, body: CommitRangeRequest
) -> ChangeAnalysisReport:
    return services.change_analysis.analyze_commit_range(
        ChangeAnalysisRequest(
            repository_id=body.repository_id,
            base_ref=body.base_ref,
            target_ref=body.target_ref,
            request_id=request_id_for(request),
        )
    )


@router.get("/{analysis_id}")
def get_analysis(services: Services, analysis_id: str) -> ChangeAnalysisReport:
    return services.change_analysis.get(analysis_id)


# `response_model=None` because the three formats return different media
# types; the shape is chosen by the query parameter, not by one schema.
@router.get("/{analysis_id}/report", response_model=None)
def get_report(
    services: Services,
    analysis_id: str,
    report_format: ReportFormat = _DEFAULT_FORMAT,
) -> JSONResponse | PlainTextResponse:
    """Render a stored analysis. Every format reads the same persisted rows."""
    report = services.change_analysis.get(analysis_id)
    if report_format == "markdown":
        return PlainTextResponse(
            render_markdown(report), media_type="text/markdown; charset=utf-8"
        )
    if report_format == "sarif":
        return JSONResponse(render_sarif(report))
    return JSONResponse(report.model_dump(mode="json"))
