"""完整合同审查 DAG 的结构化数据契约。

Agent 草稿只携带段落编号；服务层验证后再回填原文引用，避免模型伪造证据。
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.contract_background import ContractBackgroundResponse, SourceRef


class ContractTypeCode(StrEnum):
    SALE = "sale"
    UTILITY_SUPPLY = "utility_supply"
    GIFT = "gift"
    LOAN = "loan"
    LEASE = "lease"
    FINANCE_LEASE = "finance_lease"
    WORK_CONTRACT = "work_contract"
    CONSTRUCTION = "construction"
    TRANSPORT = "transport"
    TECHNOLOGY = "technology"
    CUSTODY = "custody"
    WAREHOUSING = "warehousing"
    ENTRUSTMENT = "entrustment"
    PROPERTY_SERVICE = "property_service"
    COMMISSION_AGENCY = "commission_agency"
    INTERMEDIARY = "intermediary"
    PARTNERSHIP = "partnership"
    GUARANTEE = "guarantee"
    FACTORING = "factoring"
    EMPLOYMENT = "employment"
    NDA = "nda"
    SAAS_SOFTWARE_SERVICE = "saas_software_service"
    EQUITY_TRANSFER = "equity_transfer"
    PROCUREMENT_FRAMEWORK = "procurement_framework"
    FRANCHISE = "franchise"
    INVESTMENT_CAPITAL_INCREASE = "investment_capital_increase"
    ASSET_BUSINESS_ACQUISITION = "asset_business_acquisition"
    CREDIT_ASSIGNMENT_DEBT_ASSUMPTION = "credit_assignment_debt_assumption"
    MORTGAGE_PLEDGE = "mortgage_pledge"
    IP_LICENSE = "ip_license"
    INSURANCE = "insurance"
    JOINT_VENTURE = "joint_venture"
    DPA = "dpa"
    ASSET_CUSTODY = "asset_custody"


ReviewPerspective = Literal["neutral", "party_a", "party_b"]
ReviewStatus = Literal["complete", "partial"]
ModuleStatus = Literal["succeeded", "failed", "skipped"]
RiskLevel = Literal["fatal", "high", "medium", "low"]
SigningRecommendation = Literal["do_not_sign", "conditional", "can_sign_after_review"]
ReviewModule = Literal[
    "party_qualification",
    "form_structure",
    "general_substantive",
    "related_document_comparison",
    "contract_type_special",
]


class AgentFindingDraft(BaseModel):
    """单个审查 Agent 返回的风险草稿。"""

    risk_level: RiskLevel
    contract_location: str
    issue: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    impact: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)
    negotiation_strategy: str = Field(min_length=1)
    paragraph_ids: list[str] = Field(default_factory=list)


class BranchAgentDraft(BaseModel):
    summary: str = Field(min_length=1)
    findings: list[AgentFindingDraft] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class AgentContractTypeSelection(BaseModel):
    code: ContractTypeCode
    is_primary: bool
    reason: str = Field(min_length=1)
    paragraph_ids: list[str] = Field(default_factory=list)


class FormStructureAgentDraft(BranchAgentDraft):
    contract_types: list[AgentContractTypeSelection] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def _require_one_primary_type(self) -> "FormStructureAgentDraft":
        if sum(item.is_primary for item in self.contract_types) != 1:
            raise ValueError("contract_types must contain exactly one primary type")
        if len({item.code for item in self.contract_types}) != len(self.contract_types):
            raise ValueError("contract_types cannot contain duplicate codes")
        return self


class ContractTypeSelection(BaseModel):
    code: ContractTypeCode
    label: str
    rule_pack: str
    is_primary: bool
    reason: str
    source_refs: list[SourceRef] = Field(default_factory=list)


class ContractTypeSelectionDraft(BaseModel):
    """服务层解析证据后保存的类型确认结果。"""

    summary: str
    contract_types: list[ContractTypeSelection] = Field(min_length=1, max_length=3)
    findings: list["ReviewFinding"] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class ReviewFinding(BaseModel):
    finding_id: str
    module: ReviewModule
    risk_level: RiskLevel
    contract_location: str
    issue: str
    basis: str
    impact: str
    suggestion: str
    negotiation_strategy: str
    source_refs: list[SourceRef] = Field(default_factory=list)
    source_finding_ids: list[str] = Field(default_factory=list)
    requires_human_review: bool = True


class ReviewModuleError(BaseModel):
    code: str
    message: str


class ReviewModuleResult(BaseModel):
    module: ReviewModule
    status: ModuleStatus
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    error: ReviewModuleError | None = None


class ConsolidatedFindingDraft(BaseModel):
    """报告 Agent 只能选择已有 finding ID 的分组，不得重写风险事实。"""

    model_config = ConfigDict(extra="forbid")

    source_finding_ids: list[str] = Field(min_length=1)


class ReportAgentDraft(BaseModel):
    executive_summary: str = Field(min_length=1)
    overall_risk_level: RiskLevel
    signing_recommendation: SigningRecommendation
    preconditions: list[str] = Field(default_factory=list)
    findings: list[ConsolidatedFindingDraft] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ContractReviewReport(BaseModel):
    executive_summary: str
    overall_risk_level: RiskLevel
    signing_recommendation: SigningRecommendation
    preconditions: list[str] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    failed_modules: list[ReviewModule] = Field(default_factory=list)


class ReportDocumentInfo(BaseModel):
    """合同审查报告 PDF 的对外元数据，不承载二进制正文。"""

    format: Literal["pdf"] = "pdf"
    filename: str
    content_type: Literal["application/pdf"] = "application/pdf"
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_at: datetime
    download_path: str

    @field_validator("generated_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        # 报告生成时间用于文件追踪与审计，禁止保存语义不明确的朴素时间。
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include timezone")
        return value


class ContractReviewReportResponse(BaseModel):
    module: Literal["contract_review_report"]
    task_id: str
    status: ReviewStatus
    review_perspective: ReviewPerspective
    background: ContractBackgroundResponse
    contract_types: list[ContractTypeSelection] = Field(default_factory=list, max_length=3)
    modules: list[ReviewModuleResult]
    report: ContractReviewReport
    disclaimer: str
    # 图内部状态和旧快照没有 PDF 元数据时仍可正常反序列化。
    report_document: ReportDocumentInfo | None = None


class ContractReviewHistoryItem(BaseModel):
    task_id: str
    title: str | None
    status: ReviewStatus
    risk_level: RiskLevel
    created_at: datetime


class ContractReviewHistoryResponse(BaseModel):
    items: list[ContractReviewHistoryItem]


ContractTypeSelectionDraft.model_rebuild()
