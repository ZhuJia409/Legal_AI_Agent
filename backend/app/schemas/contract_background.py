"""合同背景审查使用的 Pydantic 数据模型。

模型输出草稿只保存回答文本和段落号；服务层校验段落号后，再将其转换成
包含完整原文的 API 响应结构，避免让大模型复制或改写引用内容。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ContractCategory = Literal[
    "commercial_transaction",
    "service_entrustment",
    "construction_project",
    "technology_data_ip",
    "finance_guarantee",
    "investment_ma",
    "labor_hr",
    "framework_cooperation",
    "other_unknown",
]

RelatedDocumentStatus = Literal["provided", "missing"]

# 固定目录只定义每次 Phase 0 都要回答的内容，不参与具体合同的语义判断。
BACKGROUND_QUESTION_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("commercial_purpose", "合同文本能够支持的交易目的或商业目的是什么？"),
    ("party_position", "合同双方分别处于什么合同角色或交易立场？"),
    ("counterparty_identity", "双方身份以及合同文本体现的双方关系是什么？"),
    ("amount_term_scope", "合同金额、期限、标的和交易范围是什么？"),
    ("business_focus", "合同文本体现了哪些特殊业务关注点？"),
    ("urgency_deadline", "是否存在紧迫性、履行期限或明确截止日期？"),
)

PHASE0_PITFALL_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("name_substance_mismatch", "名实不符"),
    ("letter_of_intent_effect", "意向书效力"),
    ("precontractual_liability", "隐形缔约过失责任触发点"),
)

RELATED_DOCUMENT_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("related_document_checklist", "关联文件清单"),
    ("negotiation_minutes", "谈判纪要/会议记录"),
    ("emails", "邮件往来"),
    ("chat_records", "聊天记录"),
    ("framework_master_contract", "框架协议/主合同"),
    ("tender_award_documents", "招标文件及中标通知书"),
    ("technical_specification", "技术规格/SOW/需求文档"),
    ("historical_contracts", "历史合同"),
    ("due_diligence_report", "尽职调查报告"),
    ("project_approval_documents", "项目立项/内部审批文件"),
    ("counterparty_materials", "相对方公示材料/报价单"),
)


class SourceRef(BaseModel):
    """由服务层根据模型返回的段落号解析出的完整证据引用。"""

    paragraph_id: str = Field(description="稳定的合同段落或表格行标识。")
    clause_path: str | None = Field(
        default=None,
        description="识别到的合同条款路径；无法识别时为空。",
    )
    quote: str = Field(description="服务层从对应段落回填的完整原文。")


class EvidenceText(BaseModel):
    """一项经过段落号校验并回填原文的背景事实。"""

    text: str | None = Field(default=None, description="由 source_refs 支持的事实文本。")
    source_refs: list[SourceRef] = Field(default_factory=list)


class BackgroundCard(BaseModel):
    """最终响应中的六项背景信息卡。"""

    commercial_purpose: EvidenceText = Field(default_factory=EvidenceText)
    party_position: EvidenceText = Field(default_factory=EvidenceText)
    counterparty_identity: EvidenceText = Field(default_factory=EvidenceText)
    amount_term_scope: EvidenceText = Field(default_factory=EvidenceText)
    business_focus: EvidenceText = Field(default_factory=EvidenceText)
    urgency_deadline: EvidenceText = Field(default_factory=EvidenceText)

    @field_validator(
        "commercial_purpose",
        "party_position",
        "counterparty_identity",
        "amount_term_scope",
        "business_focus",
        "urgency_deadline",
        mode="before",
    )
    @classmethod
    def _coerce_legacy_text(cls, value: Any) -> Any:
        """兼容已有测试和持久化代码中的旧版纯文本输入。"""

        if value is None:
            return {"text": None, "source_refs": []}
        if isinstance(value, str):
            return {"text": value, "source_refs": []}
        return value


class AgentEvidenceText(BaseModel):
    """模型回答一项问题时只需返回文本和对应段落号。"""

    text: str | None
    paragraph_ids: list[str]

    @field_validator("text")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def _validate_evidence_pair(self) -> "AgentEvidenceText":
        # 有答案必须有证据；没有答案也不能附带无法解释的段落号。
        if self.text is not None and not self.paragraph_ids:
            raise ValueError("background answer requires at least one paragraph_id")
        if self.text is None and self.paragraph_ids:
            raise ValueError("empty background answer cannot include paragraph_ids")
        return self


class AgentBackgroundCard(BaseModel):
    """模型必须完整回答的六项固定背景问题。"""

    commercial_purpose: AgentEvidenceText
    party_position: AgentEvidenceText
    counterparty_identity: AgentEvidenceText
    amount_term_scope: AgentEvidenceText
    business_focus: AgentEvidenceText
    urgency_deadline: AgentEvidenceText


class AgentPitfallAssessment(BaseModel):
    """模型对一项固定 Phase 0 陷阱的判断。"""

    risk: str = Field(min_length=1)
    review_action: str = Field(min_length=1)
    paragraph_ids: list[str]


class AgentPitfallAssessments(BaseModel):
    """三个陷阱使用固定字段，避免模型漏项、增项或改名。"""

    name_substance_mismatch: AgentPitfallAssessment
    letter_of_intent_effect: AgentPitfallAssessment
    precontractual_liability: AgentPitfallAssessment


class AgentRelatedDocumentStatuses(BaseModel):
    """模型根据本次实际上传文件名判断的十一类文件状态。"""

    related_document_checklist: RelatedDocumentStatus
    negotiation_minutes: RelatedDocumentStatus
    emails: RelatedDocumentStatus
    chat_records: RelatedDocumentStatus
    framework_master_contract: RelatedDocumentStatus
    tender_award_documents: RelatedDocumentStatus
    technical_specification: RelatedDocumentStatus
    historical_contracts: RelatedDocumentStatus
    due_diligence_report: RelatedDocumentStatus
    project_approval_documents: RelatedDocumentStatus
    counterparty_materials: RelatedDocumentStatus


class RelatedDocument(BaseModel):
    """Phase 0 需要收集或核对的一类关联文件。"""

    name: str
    status: RelatedDocumentStatus


class ReviewPitfall(BaseModel):
    """Phase 0 初步陷阱及其后续复核动作。"""

    name: str
    risk: str
    review_action: str
    source_refs: list[SourceRef] = Field(default_factory=list)


class ContractBackgroundAgentDraft(BaseModel):
    """LangChain Agent 必须一次性生成的完整 Phase 0 结构。"""

    summary: str = Field(min_length=1)
    contract_category: ContractCategory
    background_card: AgentBackgroundCard
    related_documents: AgentRelatedDocumentStatuses
    missing_questions: list[str]
    pitfalls: AgentPitfallAssessments


class ContractBackgroundResponse(BaseModel):
    """合同背景审查接口返回的最终数据结构。"""

    module: Literal["contract_background"]
    disclaimer: str
    summary: str
    background_card: BackgroundCard
    contract_category: ContractCategory
    related_documents: list[RelatedDocument]
    missing_questions: list[str]
    pitfalls: list[ReviewPitfall]
