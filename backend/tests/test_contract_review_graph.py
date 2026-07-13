from collections.abc import Sequence

import pytest
from pydantic import BaseModel

from app.integrations.llm.client import LLMClientError
from app.schemas.contract_background import BackgroundCard, ContractBackgroundResponse
from app.schemas.contract_review import (
    AgentContractTypeSelection,
    AgentFindingDraft,
    BranchAgentDraft,
    ConsolidatedFindingDraft,
    FormStructureAgentDraft,
    ReportAgentDraft,
    ReviewFinding,
)
from app.services.contract_background import ContractBackgroundAnalysis
from app.services.contract_review_graph import (
    AgentRunResult,
    ContractReviewGraphService,
    ParsedRelatedDocument,
    _consolidate_findings,
)


class FakeBackgroundService:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def analyze_with_raw_output(
        self,
        *,
        title: str | None,
        content: str,
        provided_related_documents: Sequence[str] = (),
    ) -> ContractBackgroundAnalysis:
        self.events.extend(["phase0:start", "phase0:end"])
        response = ContractBackgroundResponse(
            module="contract_background",
            disclaimer="需由法律专业人士复核。",
            summary="采购合同背景审查。",
            background_card=BackgroundCard(
                commercial_purpose="采购设备",
                party_position="甲方采购，乙方供货",
                counterparty_identity="合同未完整披露",
                amount_term_scope="采购通用设备",
                business_focus="交付与验收",
                urgency_deadline="未确认",
            ),
            contract_category="commercial_transaction",
            related_documents=[],
            missing_questions=[],
            pitfalls=[],
        )
        return ContractBackgroundAnalysis(response=response, raw_output={"phase": "phase0"})


class FakeReviewAgentRunner:
    def __init__(
        self,
        events: list[str],
        fail_modules: set[str] | None = None,
        missing_evidence_by_module: dict[str, list[str]] | None = None,
    ) -> None:
        self.events = events
        self.fail_modules = fail_modules or set()
        self.missing_evidence_by_module = missing_evidence_by_module or {}
        self.prompts: dict[str, str] = {}

    async def run(
        self,
        *,
        module: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        task_id: str,
    ) -> AgentRunResult:
        self.events.append(f"{module}:start")
        self.prompts[module] = user_prompt
        if module in self.fail_modules:
            self.events.append(f"{module}:failed")
            raise LLMClientError(f"{module} failed")

        if module == "form_structure":
            output: BaseModel = FormStructureAgentDraft(
                summary="合同形式基本完整，主类型为买卖合同。",
                contract_types=[
                    AgentContractTypeSelection(
                        code="sale",
                        is_primary=True,
                        reason="合同约定设备交付和价款支付。",
                        paragraph_ids=["p0001"],
                    )
                ],
                findings=[],
                missing_evidence=[],
            )
        elif module == "report":
            output = ReportAgentDraft(
                executive_summary="本合同存在需补充核验的事项。",
                overall_risk_level="medium",
                signing_recommendation="conditional",
                preconditions=["完成缺失材料核验"],
                findings=[],
                limitations=[],
            )
        else:
            findings = []
            if module == "party_qualification":
                findings = [
                    AgentFindingDraft(
                        risk_level="high",
                        contract_location="合同首部",
                        issue="签约代表授权文件缺失",
                        basis="合同仅列明代表姓名。",
                        impact="可能产生代理权限争议。",
                        suggestion="补充授权委托书。",
                        negotiation_strategy="将授权文件作为生效条件。",
                        paragraph_ids=["p0001"],
                    )
                ]
            output = BranchAgentDraft(
                summary=f"{module} 已完成",
                findings=findings,
                missing_evidence=self.missing_evidence_by_module.get(module, []),
            )

        self.events.append(f"{module}:end")
        return AgentRunResult(output=output, raw_output=output.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_contract_review_graph_respects_type_and_report_barriers() -> None:
    events: list[str] = []
    runner = FakeReviewAgentRunner(events)
    service = ContractReviewGraphService(FakeBackgroundService(events), runner)

    analysis = await service.analyze(
        task_id="task-1",
        title="采购合同",
        content="采购合同\n\n甲方向乙方采购设备。",
        review_perspective="party_a",
    )

    assert events.index("phase0:end") < events.index("party_qualification:start")
    assert events.index("form_structure:end") < events.index("contract_type_special:start")
    assert all(
        events.index(f"{module}:end") < events.index("report:start")
        for module in (
            "party_qualification",
            "general_substantive",
            "contract_type_special",
        )
    )
    assert analysis.response.status == "complete"
    assert analysis.response.contract_types[0].code.value == "sale"
    assert "买卖合同规则包" in runner.prompts["contract_type_special"]


@pytest.mark.asyncio
async def test_contract_review_graph_returns_partial_report_when_branch_fails() -> None:
    events: list[str] = []
    runner = FakeReviewAgentRunner(events, fail_modules={"party_qualification"})
    service = ContractReviewGraphService(FakeBackgroundService(events), runner)

    analysis = await service.analyze(
        task_id="task-2",
        title="采购合同",
        content="采购合同\n\n甲方向乙方采购设备。",
        review_perspective="neutral",
    )

    party_result = next(
        item for item in analysis.response.modules if item.module == "party_qualification"
    )
    assert analysis.response.status == "partial"
    assert party_result.status == "failed"
    assert "party_qualification" in analysis.response.report.failed_modules
    assert "不可作为签署依据" in analysis.response.disclaimer


@pytest.mark.asyncio
async def test_contract_review_graph_skips_related_comparison_without_files() -> None:
    events: list[str] = []
    runner = FakeReviewAgentRunner(events)
    service = ContractReviewGraphService(FakeBackgroundService(events), runner)

    analysis = await service.analyze(
        task_id="task-3",
        title="采购合同",
        content="采购合同\n\n甲方向乙方采购设备。",
        review_perspective="neutral",
    )

    related_result = next(
        item
        for item in analysis.response.modules
        if item.module == "related_document_comparison"
    )
    assert related_result.status == "skipped"
    assert "related_document_comparison" not in runner.prompts
    assert analysis.response.status == "complete"


@pytest.mark.asyncio
async def test_contract_review_graph_passes_related_content_to_comparison_agent() -> None:
    events: list[str] = []
    runner = FakeReviewAgentRunner(events)
    service = ContractReviewGraphService(FakeBackgroundService(events), runner)

    await service.analyze(
        task_id="task-4",
        title="采购合同",
        content="采购合同\n\n甲方向乙方采购设备。",
        review_perspective="neutral",
        related_documents=[
            ParsedRelatedDocument(filename="技术规格.docx", content="设备应支持三年质保。")
        ],
    )

    assert "技术规格.docx" in runner.prompts["related_document_comparison"]
    assert "设备应支持三年质保" in runner.prompts["related_document_comparison"]


def test_report_consolidation_uses_only_original_finding_content() -> None:
    sources = [
        ReviewFinding(
            finding_id="party_qualification-001",
            module="party_qualification",
            risk_level="high",
            contract_location="合同首部",
            issue="签约代表授权文件缺失",
            basis="合同仅列明代表姓名。",
            impact="可能产生代理权限争议。",
            suggestion="补充授权委托书。",
            negotiation_strategy="将授权文件作为生效条件。",
        ),
        ReviewFinding(
            finding_id="form_structure-001",
            module="form_structure",
            risk_level="medium",
            contract_location="签署页",
            issue="签署日期未填写",
            basis="签署页日期栏为空。",
            impact="可能影响生效时间判断。",
            suggestion="签署时填写完整日期。",
            negotiation_strategy="要求双方同日签署并留存版本。",
        ),
    ]
    draft = ReportAgentDraft(
        executive_summary="需补充签署证据。",
        overall_risk_level="high",
        signing_recommendation="conditional",
        findings=[
            ConsolidatedFindingDraft(
                source_finding_ids=[
                    "party_qualification-001",
                    "form_structure-001",
                ]
            )
        ],
    )

    findings = _consolidate_findings(draft, sources)

    assert len(findings) == 1
    assert findings[0].risk_level == "high"
    assert findings[0].source_finding_ids == [
        "party_qualification-001",
        "form_structure-001",
    ]
    assert findings[0].issue == "签约代表授权文件缺失；签署日期未填写"
    assert findings[0].suggestion == "补充授权委托书；签署时填写完整日期。"


def test_report_consolidation_rejects_reusing_a_finding_id() -> None:
    source = ReviewFinding(
        finding_id="party_qualification-001",
        module="party_qualification",
        risk_level="high",
        contract_location="合同首部",
        issue="签约代表授权文件缺失",
        basis="合同仅列明代表姓名。",
        impact="可能产生代理权限争议。",
        suggestion="补充授权委托书。",
        negotiation_strategy="将授权文件作为生效条件。",
    )
    draft = ReportAgentDraft(
        executive_summary="需补充签署证据。",
        overall_risk_level="high",
        signing_recommendation="conditional",
        findings=[
            ConsolidatedFindingDraft(
                source_finding_ids=["party_qualification-001"]
            ),
            ConsolidatedFindingDraft(
                source_finding_ids=["party_qualification-001"]
            ),
        ],
    )

    with pytest.raises(LLMClientError, match="reused finding_id"):
        _consolidate_findings(draft, [source])


@pytest.mark.asyncio
async def test_report_deterministically_collects_module_missing_evidence() -> None:
    events: list[str] = []
    runner = FakeReviewAgentRunner(
        events,
        missing_evidence_by_module={
            "general_substantive": ["双方盖章版附件清单"],
        },
    )
    service = ContractReviewGraphService(FakeBackgroundService(events), runner)

    analysis = await service.analyze(
        task_id="task-limitations",
        title="采购合同",
        content="采购合同\n\n甲方向乙方采购设备。",
        review_perspective="neutral",
    )

    assert "通用实质审查缺失证据：双方盖章版附件清单" in analysis.response.report.limitations
    assert "关联文件比对缺失证据：可用于比对的关联文件" in analysis.response.report.limitations
