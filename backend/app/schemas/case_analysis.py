"""案件分析并联图使用的严格结构化模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RiskLevel = Literal["unknown", "low", "medium", "high"]
AnalysisStatus = Literal["complete", "partial"]
StageStatus = Literal["succeeded", "needs_input", "failed", "skipped"]
CaseStageCode = Literal[
    "intake_screening",
    "fact_reconstruction",
    "evidence_review",
    "legal_classification",
    "deep_analysis",
    "risk_assessment",
    "strategy_options",
    "document_draft",
    "deadline_management",
]
CASE_ANALYSIS_STAGE_ORDER: tuple[CaseStageCode, ...] = (
    "intake_screening",
    "fact_reconstruction",
    "evidence_review",
    "legal_classification",
    "deep_analysis",
    "risk_assessment",
    "strategy_options",
    "document_draft",
    "deadline_management",
)
RiskDimension = Literal["internal", "opponent", "execution_cost"]
StrategyMode = Literal["aggressive", "balanced", "conservative"]

CASE_ANALYSIS_DISCLAIMER = (
    "本结果由人工智能基于已提供案件材料生成，仅供案件分析参考，不构成确定性法律结论；"
    "事实认定、证据判断、法律适用、期限计算和诉讼策略必须由专业法律人士结合完整材料与"
    "现行有效法律复核。"
)


class StrictCaseModel(BaseModel):
    """禁止模型悄然增加字段，避免错误结构被当作有效法律输出。"""

    model_config = ConfigDict(extra="forbid")


class CaseStageError(StrictCaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class CaseSourceRef(StrictCaseModel):
    paragraph_id: str = Field(pattern=r"^p\d{4,}$")
    quote: str = Field(min_length=1)


class AgentFindingDraft(StrictCaseModel):
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    paragraph_ids: list[str]


class AgentPartyDraft(StrictCaseModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    paragraph_ids: list[str]


class AgentClaimDraft(StrictCaseModel):
    claimant: str = Field(min_length=1)
    request: str = Field(min_length=1)
    paragraph_ids: list[str]


class AgentTimelineEventDraft(StrictCaseModel):
    date: str = Field(min_length=1)
    event: str = Field(min_length=1)
    parties: list[str]
    paragraph_ids: list[str]


class AgentDeadlineDraft(StrictCaseModel):
    name: str = Field(min_length=1)
    trigger_date: str | None = None
    deadline: str | None = None
    uncertainty: str = Field(min_length=1)
    paragraph_ids: list[str]

    @field_validator("trigger_date")
    @classmethod
    def _normalize_trigger_date(cls, value: str | None) -> str | None:
        # 空白起算日等同于缺失，必须交由后续期限配对校验处理。
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def _reject_computed_deadline_without_trigger(self) -> AgentDeadlineDraft:
        # 缺少起算日时，模型不得把推测日期包装成精确法律期限。
        if self.trigger_date is None and self.deadline is not None:
            raise ValueError("deadline requires a trigger_date")
        return self


class AgentIntakeDraft(StrictCaseModel):
    summary: str = Field(min_length=1)
    parties: list[AgentPartyDraft]
    claims: list[AgentClaimDraft]
    case_route: str | None = None
    red_flags: list[AgentFindingDraft]
    missing_information: list[str]


class AgentFactDraft(StrictCaseModel):
    summary: str = Field(min_length=1)
    timeline: list[AgentTimelineEventDraft]
    key_facts: list[AgentFindingDraft]
    conflicts: list[AgentFindingDraft]
    missing_information: list[str]


class AgentDeadlineScanDraft(StrictCaseModel):
    summary: str = Field(min_length=1)
    deadlines: list[AgentDeadlineDraft]
    missing_information: list[str]


class AgentEvidenceDraft(StrictCaseModel):
    summary: str = Field(min_length=1)
    evidence_clues: list[AgentFindingDraft]
    gaps: list[AgentFindingDraft]
    reinforcement_plan: list[str]
    missing_information: list[str]


class AgentLegalRelationDraft(StrictCaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    paragraph_ids: list[str]


class AgentCandidateCauseDraft(StrictCaseModel):
    name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    paragraph_ids: list[str]


class AgentLegalClassificationDraft(StrictCaseModel):
    summary: str = Field(min_length=1)
    legal_relations: list[AgentLegalRelationDraft]
    candidate_causes: list[AgentCandidateCauseDraft]
    procedure_questions: list[str]
    missing_information: list[str]


class AgentIssueSpecDraft(StrictCaseModel):
    issue_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    question: str = Field(min_length=1)
    paragraph_ids: list[str] = Field(min_length=1)


class AgentIssueIdentificationDraft(StrictCaseModel):
    summary: str = Field(min_length=1)
    issues: list[AgentIssueSpecDraft]
    missing_information: list[str]


class AgentIssueAnalysisDraft(StrictCaseModel):
    issue_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    analysis: str = Field(min_length=1)
    positions: list[str]
    uncertainties: list[str]
    paragraph_ids: list[str] = Field(min_length=1)
    missing_information: list[str]


class AgentRiskItemDraft(StrictCaseModel):
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    risk_level: RiskLevel
    mitigation: str = Field(min_length=1)
    paragraph_ids: list[str]


class AgentRiskDraft(StrictCaseModel):
    dimension: RiskDimension
    summary: str = Field(min_length=1)
    risk_level: RiskLevel
    risks: list[AgentRiskItemDraft]
    missing_information: list[str]


class AgentStrategyDraft(StrictCaseModel):
    mode: StrategyMode
    summary: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    steps: list[str]
    prerequisites: list[str]
    risks: list[str]
    missing_information: list[str]


class CaseFinding(StrictCaseModel):
    title: str
    detail: str
    source_refs: list[CaseSourceRef]


class CaseParty(StrictCaseModel):
    name: str
    role: str
    source_refs: list[CaseSourceRef]


class CaseClaim(StrictCaseModel):
    claimant: str
    request: str
    source_refs: list[CaseSourceRef]


class CaseTimelineEvent(StrictCaseModel):
    date: str
    event: str
    parties: list[str]
    source_refs: list[CaseSourceRef]


class CaseDeadline(StrictCaseModel):
    name: str
    trigger_date: str | None
    deadline: str | None
    uncertainty: str
    source_refs: list[CaseSourceRef]


class CaseLegalRelation(StrictCaseModel):
    name: str
    description: str
    source_refs: list[CaseSourceRef]


class CaseCandidateCause(StrictCaseModel):
    name: str
    reason: str
    source_refs: list[CaseSourceRef]


class CaseIssueAnalysis(StrictCaseModel):
    issue_id: str
    title: str
    analysis: str
    positions: list[str]
    uncertainties: list[str]
    missing_information: list[str]
    source_refs: list[CaseSourceRef]


class CaseRiskItem(StrictCaseModel):
    dimension: RiskDimension
    title: str
    detail: str
    risk_level: RiskLevel
    mitigation: str
    source_refs: list[CaseSourceRef]


class CaseStrategy(StrictCaseModel):
    mode: StrategyMode
    summary: str
    objective: str
    steps: list[str]
    prerequisites: list[str]
    risks: list[str]
    missing_information: list[str]


class CaseStageBase(StrictCaseModel):
    stage: CaseStageCode
    status: StageStatus
    summary: str
    missing_information: list[str]
    requires_human_review: bool = True
    error: CaseStageError | None = None

    @model_validator(mode="after")
    def _require_human_review(self) -> CaseStageBase:
        if not self.requires_human_review:
            raise ValueError("case analysis stages always require human review")
        return self


class IntakeStageResult(CaseStageBase):
    stage: Literal["intake_screening"]
    parties: list[CaseParty]
    claims: list[CaseClaim]
    case_route: str | None
    red_flags: list[CaseFinding]


class FactStageResult(CaseStageBase):
    stage: Literal["fact_reconstruction"]
    timeline: list[CaseTimelineEvent]
    key_facts: list[CaseFinding]
    conflicts: list[CaseFinding]


class EvidenceStageResult(CaseStageBase):
    stage: Literal["evidence_review"]
    evidence_clues: list[CaseFinding]
    gaps: list[CaseFinding]
    reinforcement_plan: list[str]


class LegalStageResult(CaseStageBase):
    stage: Literal["legal_classification"]
    legal_relations: list[CaseLegalRelation]
    candidate_causes: list[CaseCandidateCause]
    procedure_questions: list[str]


class DeepAnalysisStageResult(CaseStageBase):
    stage: Literal["deep_analysis"]
    issues: list[CaseIssueAnalysis]


class RiskStageResult(CaseStageBase):
    stage: Literal["risk_assessment"]
    overall_risk_level: RiskLevel
    risks: list[CaseRiskItem]


class StrategyStageResult(CaseStageBase):
    stage: Literal["strategy_options"]
    strategies: list[CaseStrategy]


class DocumentDraftStageResult(CaseStageBase):
    stage: Literal["document_draft"]
    draft_title: str
    draft_sections: list[str]
    quality_checks: list[str]


class DeadlineStageResult(CaseStageBase):
    stage: Literal["deadline_management"]
    deadlines: list[CaseDeadline]


CaseStageResult = Annotated[
    IntakeStageResult
    | FactStageResult
    | EvidenceStageResult
    | LegalStageResult
    | DeepAnalysisStageResult
    | RiskStageResult
    | StrategyStageResult
    | DocumentDraftStageResult
    | DeadlineStageResult,
    Field(discriminator="stage"),
]


class CaseAnalysisReport(StrictCaseModel):
    executive_summary: str
    overall_risk_level: RiskLevel
    key_findings: list[str]
    recommended_actions: list[str]
    limitations: list[str]
    failed_stages: list[CaseStageCode]


class CaseDraftDocumentInfo(StrictCaseModel):
    """案件文书草稿的可下载元数据，不暴露 MinIO 对象地址。"""

    format: Literal["docx"] = "docx"
    filename: str = Field(min_length=1)
    content_type: Literal[
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_at: datetime
    download_path: str = Field(min_length=1)

    @field_validator("generated_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include timezone")
        return value


class CaseAnalysisResponse(StrictCaseModel):
    module: Literal["case_analysis"] = "case_analysis"
    analysis_id: str
    status: AnalysisStatus
    summary: str
    risk_level: RiskLevel
    findings: list[str]
    suggestions: list[str]
    stages: list[CaseStageResult]
    report: CaseAnalysisReport
    draft_document: CaseDraftDocumentInfo | None = None
    disclaimer: str = CASE_ANALYSIS_DISCLAIMER

    @model_validator(mode="after")
    def _require_fixed_stage_order(self) -> CaseAnalysisResponse:
        # 公开响应必须保留九阶段契约，避免漏项、重复或乱序被前端误解。
        stage_order = tuple(stage.stage for stage in self.stages)
        if stage_order != CASE_ANALYSIS_STAGE_ORDER:
            raise ValueError("case analysis stages must match the fixed stage order")
        return self


class CaseAnalysisHistoryItem(StrictCaseModel):
    analysis_id: str
    title: str | None
    status: AnalysisStatus
    risk_level: RiskLevel
    created_at: datetime


class CaseAnalysisHistoryResponse(StrictCaseModel):
    items: list[CaseAnalysisHistoryItem]
