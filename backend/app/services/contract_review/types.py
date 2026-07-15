from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel
from typing_extensions import TypedDict

from app.schemas.contract_review import (
    ContractPdfDocument,
    ContractReviewReportResponse,
    ContractTypeSelection,
    ReviewModuleResult,
    ReviewPerspective,
)
from app.schemas.contract_review.background import ContractBackgroundResponse


@dataclass(frozen=True)
class ParsedRelatedDocument:
    filename: str
    content: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class EvidenceSegment:
    paragraph_id: str
    document_name: str | None
    clause_path: str | None
    text: str


@dataclass(frozen=True)
class AgentRunResult:
    output: BaseModel
    raw_output: dict[str, Any]


@dataclass(frozen=True)
class ContractReviewGraphAnalysis:
    response: ContractReviewReportResponse
    pdf_form: ContractPdfDocument
    raw_outputs: list[dict[str, Any]]


class ContractReviewGraphState(TypedDict, total=False):
    task_id: str
    title: str | None
    content: str
    review_perspective: ReviewPerspective
    related_documents: list[ParsedRelatedDocument]
    evidence_segments: list[EvidenceSegment]
    background: ContractBackgroundResponse
    party_result: ReviewModuleResult
    form_result: ReviewModuleResult
    general_result: ReviewModuleResult
    related_result: ReviewModuleResult
    special_result: ReviewModuleResult
    contract_types: list[ContractTypeSelection]
    report_response: ContractReviewReportResponse
    pdf_form: ContractPdfDocument
    raw_outputs: Annotated[list[dict[str, Any]], operator.add]
