"""案件分析九阶段并联 LangGraph。"""

from __future__ import annotations

import json
import logging
import operator
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, ValidationError
from typing_extensions import TypedDict

from app.integrations.llm.client import LLMClientError, LLMConfigurationError
from app.schemas.case_analysis import (
    CASE_ANALYSIS_DISCLAIMER,
    AgentCaseDocumentFormDraft,
    AgentDeadlineScanDraft,
    AgentEvidenceDraft,
    AgentFactDraft,
    AgentFindingDraft,
    AgentIntakeDraft,
    AgentIssueAnalysisDraft,
    AgentIssueIdentificationDraft,
    AgentIssueSpecDraft,
    AgentLegalClassificationDraft,
    AgentRiskDraft,
    AgentStrategyDraft,
    CaseAnalysisReport,
    CaseAnalysisResponse,
    CaseCandidateCause,
    CaseClaim,
    CaseDeadline,
    CaseDocumentFact,
    CaseDocumentForm,
    CaseFinding,
    CaseIssueAnalysis,
    CaseLegalRelation,
    CaseParty,
    CaseRiskItem,
    CaseStageCode,
    CaseStageError,
    CaseStrategy,
    CaseTimelineEvent,
    DeadlineStageResult,
    DeepAnalysisStageResult,
    DocumentDraftStageResult,
    EvidenceStageResult,
    FactStageResult,
    IntakeStageResult,
    LegalStageResult,
    RiskLevel,
    RiskStageResult,
    StrategyStageResult,
)
from app.services.case_analysis_agents import (
    CaseAnalysisAgentRunnerProtocol,
    CaseAnalysisStructuredOutputError,
)
from app.services.case_analysis_evidence import (
    CaseEvidenceSegment,
    UnknownCaseSourceError,
    format_case_evidence,
    resolve_source_refs,
    segment_case_material,
)

_SYSTEM_PROMPT = """
你是严谨的中国法律案件材料分析助手。你只能依据用户提供的编号材料段落工作，不得补造
事实、证据、法条、案例、客户立场或程序日期。首版未接入外部法律检索，因此不得声称已
核验现行法或类案。所有结论都必须是中立、条件化且等待专业法律人士复核的分析草稿。
不得输出精确胜诉概率、任何胜诉百分比或其他伪精确的案件结果预测。
引用只能返回材料中真实存在的 paragraph_id，不要复制原文，不要输出 Markdown。
""".strip()

_RISK_DIMENSIONS = ("internal", "opponent", "execution_cost")
_STRATEGY_MODES = ("aggressive", "balanced", "conservative")

# 服务层保留不可绕过的正文硬上限，避免调用方跳过 API 校验后触发超长模型请求。
_DEFAULT_MAX_CASE_CONTENT_CHARS = 60_000
_MAX_CONFIGURABLE_CASE_CONTENT_CHARS = 200_000
_DEFAULT_RECURSION_LIMIT = 40
_MAX_CONFIGURABLE_RECURSION_LIMIT = 200
_MAX_ISSUES = 5
_EXPECTED_NODE_ERRORS = (
    LLMClientError,
    UnknownCaseSourceError,
    ValidationError,
)

logger = logging.getLogger("legal_ai.services.case_analysis_graph")


class CaseAnalysisCriticalStageError(LLMClientError):
    """基础阶段失败，剩余结果不足以形成可信案件分析。"""

    def __init__(self, stage: str) -> None:
        super().__init__(f"critical case analysis stage failed: {stage}")
        self.stage = stage


@dataclass(frozen=True, slots=True)
class RiskBranchResult:
    dimension: Literal["internal", "opponent", "execution_cost"]
    summary: str
    risk_level: RiskLevel
    risks: tuple[CaseRiskItem, ...]
    missing_information: tuple[str, ...]


class CaseAnalysisGraphState(TypedDict, total=False):
    analysis_id: str
    title: str | None
    content: str
    segments: tuple[CaseEvidenceSegment, ...]
    intake_result: IntakeStageResult
    fact_result: FactStageResult
    deadline_result: DeadlineStageResult
    evidence_result: EvidenceStageResult
    legal_result: LegalStageResult
    issue_specs: list[AgentIssueSpecDraft]
    issue_identification_missing: list[str]
    issue_results: Annotated[list[CaseIssueAnalysis], operator.add]
    issue_failures: Annotated[list[CaseStageError], operator.add]
    risk_results: Annotated[list[RiskBranchResult], operator.add]
    risk_failures: Annotated[list[CaseStageError], operator.add]
    strategy_results: Annotated[list[CaseStrategy], operator.add]
    strategy_failures: Annotated[list[CaseStageError], operator.add]
    document_form: CaseDocumentForm
    response: CaseAnalysisResponse


class CaseAnalysisGraphService:
    def __init__(
        self,
        runner: CaseAnalysisAgentRunnerProtocol,
        *,
        max_issues: int = 5,
        max_content_chars: int = _DEFAULT_MAX_CASE_CONTENT_CHARS,
        recursion_limit: int = _DEFAULT_RECURSION_LIMIT,
    ) -> None:
        if not 1 <= max_issues <= _MAX_ISSUES:
            raise ValueError(f"max_issues must be between 1 and {_MAX_ISSUES}")
        if not 1 <= max_content_chars <= _MAX_CONFIGURABLE_CASE_CONTENT_CHARS:
            raise ValueError(
                "max_content_chars must be between 1 and "
                f"{_MAX_CONFIGURABLE_CASE_CONTENT_CHARS}"
            )
        if not 1 <= recursion_limit <= _MAX_CONFIGURABLE_RECURSION_LIMIT:
            raise ValueError(
                "recursion_limit must be between 1 and "
                f"{_MAX_CONFIGURABLE_RECURSION_LIMIT}"
            )
        self.runner = runner
        self.max_issues = max_issues
        self.max_content_chars = max_content_chars
        self.recursion_limit = recursion_limit
        self.graph = self._build_graph()

    async def analyze(
        self,
        *,
        title: str | None,
        content: str,
        analysis_id: str | None = None,
    ) -> CaseAnalysisResponse:
        if len(content) > self.max_content_chars:
            raise ValueError(
                f"case material must not exceed {self.max_content_chars} characters"
            )
        resolved_id = analysis_id or str(uuid.uuid4())
        result = await self.graph.ainvoke(
            {
                "analysis_id": resolved_id,
                "title": title,
                "content": content,
                "issue_results": [],
                "issue_failures": [],
                "risk_results": [],
                "risk_failures": [],
                "strategy_results": [],
                "strategy_failures": [],
            },
            config={
                "recursion_limit": self.recursion_limit,
                "run_name": "case_analysis_parallel_dag",
                "tags": ["legal-ai-agent", "case-analysis", "parallel-dag"],
                "metadata": {"analysis_id": resolved_id, "perspective": "neutral"},
            },
        )
        return result["response"]

    def _build_graph(self):
        builder = StateGraph(CaseAnalysisGraphState)
        builder.add_node("prepare_input", self._prepare_input_node)
        builder.add_node("intake_screening", self._intake_node)
        builder.add_node("fact_reconstruction", self._fact_node)
        builder.add_node("deadline_scan", self._deadline_node)
        builder.add_node("evidence_review", self._evidence_node)
        builder.add_node("legal_classification", self._legal_node)
        builder.add_node("identify_issues", self._identify_issues_node)
        builder.add_node("issue_worker", self._issue_worker)
        builder.add_node("dispatch_risks", self._dispatch_risks_node)
        builder.add_node("risk_worker", self._risk_worker)
        builder.add_node("dispatch_strategies", self._dispatch_strategies_node)
        builder.add_node("strategy_worker", self._strategy_worker)
        builder.add_node("document_form", self._document_form_node)
        builder.add_node("build_report", self._build_report_node)

        builder.add_edge(START, "prepare_input")
        for node in ("intake_screening", "fact_reconstruction", "deadline_scan"):
            builder.add_edge("prepare_input", node)
        builder.add_edge("fact_reconstruction", "evidence_review")
        builder.add_edge("fact_reconstruction", "legal_classification")
        builder.add_edge(
            ["intake_screening", "deadline_scan", "evidence_review", "legal_classification"],
            "identify_issues",
        )
        builder.add_conditional_edges("identify_issues", self._fan_out_issues, ["issue_worker"])
        builder.add_edge("issue_worker", "dispatch_risks")
        builder.add_conditional_edges(
            "dispatch_risks", self._fan_out_risks, ["risk_worker"]
        )
        builder.add_edge("risk_worker", "dispatch_strategies")
        builder.add_conditional_edges(
            "dispatch_strategies",
            self._fan_out_strategies,
            ["strategy_worker", "document_form"],
        )
        builder.add_edge("strategy_worker", "document_form")
        builder.add_edge("document_form", "build_report")
        builder.add_edge("build_report", END)
        return builder.compile()

    def _prepare_input_node(self, state: CaseAnalysisGraphState) -> dict[str, Any]:
        segments = segment_case_material(state["content"])
        if not segments:
            raise ValueError("case material is empty")
        return {"segments": segments}

    async def _intake_node(self, state: CaseAnalysisGraphState) -> dict[str, Any]:
        try:
            draft = await self._run(
                state,
                "intake_screening",
                AgentIntakeDraft,
                "识别当事人、表面诉求、案件路由、紧急红线和缺失信息。",
            )
            return {"intake_result": _intake_result(draft, state["segments"])}
        except LLMConfigurationError:
            raise
        except _EXPECTED_NODE_ERRORS as exc:
            _log_node_failure(state, "intake_screening", exc)
            return {"intake_result": _failed_intake(exc)}

    async def _fact_node(self, state: CaseAnalysisGraphState) -> dict[str, Any]:
        try:
            draft = await self._run(
                state,
                "fact_reconstruction",
                AgentFactDraft,
                "按时间重构事实，区分关键事实、冲突事实和缺失信息。",
            )
            return {"fact_result": _fact_result(draft, state["segments"])}
        except (LLMConfigurationError, CaseAnalysisStructuredOutputError):
            raise
        except _EXPECTED_NODE_ERRORS as exc:
            _log_node_failure(state, "fact_reconstruction", exc)
            raise CaseAnalysisCriticalStageError("fact_reconstruction") from exc

    async def _deadline_node(self, state: CaseAnalysisGraphState) -> dict[str, Any]:
        try:
            draft = await self._run(
                state,
                "deadline_scan",
                AgentDeadlineScanDraft,
                "仅识别材料中的期限线索；缺少触发日期时不得计算截止日。",
            )
            return {"deadline_result": _deadline_result(draft, state["segments"])}
        except LLMConfigurationError:
            raise
        except _EXPECTED_NODE_ERRORS as exc:
            _log_node_failure(state, "deadline_scan", exc)
            return {"deadline_result": _failed_deadline(exc)}

    async def _evidence_node(self, state: CaseAnalysisGraphState) -> dict[str, Any]:
        try:
            draft = await self._run(
                state,
                "evidence_review",
                AgentEvidenceDraft,
                "基于事实结果梳理证据线索、无法判断的三性问题和补强计划。",
                extra={"facts": state["fact_result"].model_dump(mode="json")},
            )
            return {"evidence_result": _evidence_result(draft, state["segments"])}
        except LLMConfigurationError:
            raise
        except _EXPECTED_NODE_ERRORS as exc:
            _log_node_failure(state, "evidence_review", exc)
            return {"evidence_result": _failed_evidence(exc)}

    async def _legal_node(self, state: CaseAnalysisGraphState) -> dict[str, Any]:
        try:
            draft = await self._run(
                state,
                "legal_classification",
                AgentLegalClassificationDraft,
                "识别法律关系、候选案由和程序问题；不得声称已经外部检索法条或类案。",
                extra={"facts": state["fact_result"].model_dump(mode="json")},
            )
            return {"legal_result": _legal_result(draft, state["segments"])}
        except (LLMConfigurationError, CaseAnalysisStructuredOutputError):
            raise
        except _EXPECTED_NODE_ERRORS as exc:
            _log_node_failure(state, "legal_classification", exc)
            raise CaseAnalysisCriticalStageError("legal_classification") from exc

    async def _identify_issues_node(
        self, state: CaseAnalysisGraphState
    ) -> dict[str, Any]:
        try:
            draft = await self._run(
                state,
                "identify_issues",
                AgentIssueIdentificationDraft,
                f"识别最多 {self.max_issues} 个核心争议焦点，并为每项绑定材料段落。",
                extra={
                    "intake": state["intake_result"].model_dump(mode="json"),
                    "facts": state["fact_result"].model_dump(mode="json"),
                    "evidence": state["evidence_result"].model_dump(mode="json"),
                    "legal": state["legal_result"].model_dump(mode="json"),
                },
            )
            model_issues = list(draft.issues[: self.max_issues])
            if not model_issues:
                raise CaseAnalysisStructuredOutputError(
                    "identify_issues returned no dispute issues"
                )
            # 模型 issue_id 不进入任务名、日志或追踪元数据；服务端按稳定顺序重新编号。
            issues = [
                issue.model_copy(update={"issue_id": f"issue-{index:02d}"})
                for index, issue in enumerate(model_issues, start=1)
            ]
            for issue in issues:
                resolve_source_refs(issue.paragraph_ids, state["segments"])
            return {
                "issue_specs": issues,
                "issue_identification_missing": draft.missing_information,
            }
        except (LLMConfigurationError, CaseAnalysisStructuredOutputError):
            raise
        except _EXPECTED_NODE_ERRORS as exc:
            _log_node_failure(state, "identify_issues", exc)
            raise CaseAnalysisCriticalStageError("identify_issues") from exc

    def _fan_out_issues(self, state: CaseAnalysisGraphState) -> list[Send]:
        return [
            Send(
                "issue_worker",
                {
                    "analysis_id": state["analysis_id"],
                    "segments": state["segments"],
                    "issue_spec": issue,
                },
            )
            for issue in state["issue_specs"]
        ]

    async def _issue_worker(self, state: dict[str, Any]) -> dict[str, Any]:
        issue: AgentIssueSpecDraft = state["issue_spec"]
        segments: tuple[CaseEvidenceSegment, ...] = state["segments"]
        try:
            relevant = _select_segments(issue.paragraph_ids, segments)
            run = await self.runner.run(
                module=f"issue_analysis:{issue.issue_id}",
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=_prompt(
                    "对单个争议焦点形成双方立场、条件化分析、不确定性和待补信息。",
                    relevant,
                    {"issue": issue.model_dump(mode="json")},
                ),
                response_model=AgentIssueAnalysisDraft,
                analysis_id=state["analysis_id"],
            )
            draft = AgentIssueAnalysisDraft.model_validate(run.output.model_dump())
            if draft.issue_id != issue.issue_id:
                raise CaseAnalysisStructuredOutputError(
                    "issue worker returned mismatched issue_id"
                )
            return {"issue_results": [_issue_result(draft, segments)]}
        except LLMConfigurationError:
            raise
        except _EXPECTED_NODE_ERRORS as exc:
            _log_node_failure(state, f"issue_analysis:{issue.issue_id}", exc)
            return {"issue_failures": [_stage_error("issue_analysis_failed", exc)]}

    def _dispatch_risks_node(self, state: CaseAnalysisGraphState) -> dict[str, Any]:
        if not state.get("issue_results"):
            raise CaseAnalysisCriticalStageError("deep_analysis")
        return {}

    def _fan_out_risks(self, state: CaseAnalysisGraphState) -> list[Send]:
        return [
            Send(
                "risk_worker",
                {
                    "analysis_id": state["analysis_id"],
                    "segments": state["segments"],
                    "dimension": dimension,
                    "issue_results": state["issue_results"],
                },
            )
            for dimension in _RISK_DIMENSIONS
        ]

    async def _risk_worker(self, state: dict[str, Any]) -> dict[str, Any]:
        dimension = state["dimension"]
        segments: tuple[CaseEvidenceSegment, ...] = state["segments"]
        try:
            run = await self.runner.run(
                module=f"risk:{dimension}",
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=_prompt(
                    "按指定维度评估风险；执行与成本资料不足时必须返回 unknown 和缺失信息。",
                    segments,
                    {
                        "dimension": dimension,
                        "issues": [
                            item.model_dump(mode="json") for item in state["issue_results"]
                        ],
                    },
                ),
                response_model=AgentRiskDraft,
                analysis_id=state["analysis_id"],
            )
            draft = AgentRiskDraft.model_validate(run.output.model_dump())
            if draft.dimension != dimension:
                raise CaseAnalysisStructuredOutputError(
                    "risk worker returned mismatched dimension"
                )
            risks = tuple(
                CaseRiskItem(
                    dimension=draft.dimension,
                    title=item.title,
                    detail=item.detail,
                    risk_level=item.risk_level,
                    mitigation=item.mitigation,
                    source_refs=resolve_source_refs(item.paragraph_ids, segments),
                )
                for item in draft.risks
            )
            return {
                "risk_results": [
                    RiskBranchResult(
                        dimension=draft.dimension,
                        summary=draft.summary,
                        risk_level=draft.risk_level,
                        risks=risks,
                        missing_information=tuple(draft.missing_information),
                    )
                ]
            }
        except LLMConfigurationError:
            raise
        except _EXPECTED_NODE_ERRORS as exc:
            _log_node_failure(state, f"risk:{dimension}", exc)
            return {"risk_failures": [_stage_error("risk_analysis_failed", exc)]}

    def _dispatch_strategies_node(self, state: CaseAnalysisGraphState) -> dict[str, Any]:
        if not state.get("risk_results"):
            # 风险评估全部失败时，策略缺少必要上游依据，直接降级并避免继续调用模型。
            return {
                "strategy_failures": [
                    CaseStageError(
                        code="strategy_prerequisite_failed",
                        message="风险评估未返回有效结果，策略阶段未执行。",
                    )
                ]
            }
        return {}

    def _fan_out_strategies(
        self, state: CaseAnalysisGraphState
    ) -> list[Send] | Literal["document_form"]:
        if not state.get("risk_results"):
            return "document_form"
        risk_payload = [
            {
                "dimension": item.dimension,
                "summary": item.summary,
                "risk_level": item.risk_level,
                "missing_information": list(item.missing_information),
            }
            for item in state.get("risk_results", [])
        ]
        return [
            Send(
                "strategy_worker",
                {
                    "analysis_id": state["analysis_id"],
                    "segments": state["segments"],
                    "mode": mode,
                    "issues": state["issue_results"],
                    "risks": risk_payload,
                },
            )
            for mode in _STRATEGY_MODES
        ]

    async def _strategy_worker(self, state: dict[str, Any]) -> dict[str, Any]:
        mode = state["mode"]
        try:
            run = await self.runner.run(
                module=f"strategy:{mode}",
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=_prompt(
                    "按指定模式生成条件化方案。未明确客户立场、预算和风险偏好时不得作最终推荐。",
                    state["segments"],
                    {
                        "mode": mode,
                        "issues": [item.model_dump(mode="json") for item in state["issues"]],
                        "risks": state["risks"],
                    },
                ),
                response_model=AgentStrategyDraft,
                analysis_id=state["analysis_id"],
            )
            draft = AgentStrategyDraft.model_validate(run.output.model_dump())
            if draft.mode != mode:
                raise CaseAnalysisStructuredOutputError(
                    "strategy worker returned mismatched mode"
                )
            return {
                "strategy_results": [
                    CaseStrategy(
                        mode=draft.mode,
                        summary=draft.summary,
                        objective=draft.objective,
                        steps=draft.steps,
                        prerequisites=draft.prerequisites,
                        risks=draft.risks,
                        missing_information=draft.missing_information,
                    )
                ]
            }
        except LLMConfigurationError:
            raise
        except _EXPECTED_NODE_ERRORS as exc:
            _log_node_failure(state, f"strategy:{mode}", exc)
            return {"strategy_failures": [_stage_error("strategy_failed", exc)]}

    async def _document_form_node(
        self, state: CaseAnalysisGraphState
    ) -> dict[str, Any]:
        """用工具表单生成精简文书数据；该节点失败时不生成不可审计的文件。"""

        try:
            draft = await self._run(
                state,
                "document_form",
                AgentCaseDocumentFormDraft,
                (
                    "填写案件处理方案与文书草稿表单。只压缩已验证信息，不得生成 LaTeX、"
                    "法条、案例、精确胜诉概率或可直接提交法院的诉状。"
                ),
                extra={
                    "intake": state["intake_result"].model_dump(mode="json"),
                    "facts": state["fact_result"].model_dump(mode="json"),
                    "evidence": state["evidence_result"].model_dump(mode="json"),
                    "legal": state["legal_result"].model_dump(mode="json"),
                    "issues": [item.model_dump(mode="json") for item in state["issue_results"]],
                    "risks": [
                        {
                            "dimension": item.dimension,
                            "summary": item.summary,
                            "risk_level": item.risk_level,
                            "risks": [risk.model_dump(mode="json") for risk in item.risks],
                            "missing_information": list(item.missing_information),
                        }
                        for item in state["risk_results"]
                    ],
                    "strategies": [
                        item.model_dump(mode="json")
                        for item in state.get("strategy_results", [])
                    ],
                },
                force_tool_strategy=True,
            )
            return {
                "document_form": _document_form_result(draft, state["segments"])
            }
        except LLMConfigurationError:
            raise
        except _EXPECTED_NODE_ERRORS as exc:
            _log_node_failure(state, "document_form", exc)
            raise CaseAnalysisStructuredOutputError(
                "document_form returned invalid structured output"
            ) from exc

    def _build_report_node(self, state: CaseAnalysisGraphState) -> dict[str, Any]:
        response = _build_response(state)
        return {"response": response}

    async def _run(
        self,
        state: CaseAnalysisGraphState,
        module: str,
        response_model: type[BaseModel],
        instruction: str,
        *,
        extra: dict[str, Any] | None = None,
        force_tool_strategy: bool = False,
    ) -> BaseModel:
        run = await self.runner.run(
            module=module,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_prompt(instruction, state["segments"], extra),
            response_model=response_model,
            analysis_id=state["analysis_id"],
            force_tool_strategy=force_tool_strategy,
        )
        try:
            return response_model.model_validate(run.output.model_dump())
        except ValidationError as exc:
            raise CaseAnalysisStructuredOutputError(
                f"{module} returned invalid structured output"
            ) from exc


def _prompt(
    instruction: str,
    segments: tuple[CaseEvidenceSegment, ...] | list[CaseEvidenceSegment],
    extra: dict[str, Any] | None = None,
) -> str:
    parts = [f"任务：{instruction}", "案件材料：", format_case_evidence(segments)]
    if extra:
        parts.extend(["已验证的上游结构：", json.dumps(extra, ensure_ascii=False)])
    return "\n\n".join(parts)


def _log_node_failure(state: dict[str, Any], module: str, exc: Exception) -> None:
    # 只记录分析 ID、节点和异常类型，保留诊断线索且不泄露案件正文或 provider 响应。
    logger.warning(
        "case_analysis_node_failed analysis_id=%s module=%s error_type=%s",
        state.get("analysis_id", "unknown"),
        module,
        exc.__class__.__name__,
    )


def _select_segments(
    paragraph_ids: list[str], segments: tuple[CaseEvidenceSegment, ...]
) -> list[CaseEvidenceSegment]:
    resolve_source_refs(paragraph_ids, segments)
    selected = set(paragraph_ids)
    return [item for item in segments if item.paragraph_id in selected]


def _finding(item: AgentFindingDraft, segments: tuple[CaseEvidenceSegment, ...]) -> CaseFinding:
    return CaseFinding(
        title=item.title,
        detail=item.detail,
        source_refs=resolve_source_refs(item.paragraph_ids, segments),
    )


def _status(missing_information: list[str]) -> Literal["succeeded", "needs_input"]:
    return "needs_input" if missing_information else "succeeded"


def _intake_result(
    draft: AgentIntakeDraft, segments: tuple[CaseEvidenceSegment, ...]
) -> IntakeStageResult:
    return IntakeStageResult(
        stage="intake_screening",
        status=_status(draft.missing_information),
        summary=draft.summary,
        missing_information=draft.missing_information,
        parties=[
            CaseParty(
                name=item.name,
                role=item.role,
                source_refs=resolve_source_refs(item.paragraph_ids, segments),
            )
            for item in draft.parties
        ],
        claims=[
            CaseClaim(
                claimant=item.claimant,
                request=item.request,
                source_refs=resolve_source_refs(item.paragraph_ids, segments),
            )
            for item in draft.claims
        ],
        case_route=draft.case_route,
        red_flags=[_finding(item, segments) for item in draft.red_flags],
    )


def _fact_result(
    draft: AgentFactDraft, segments: tuple[CaseEvidenceSegment, ...]
) -> FactStageResult:
    return FactStageResult(
        stage="fact_reconstruction",
        status=_status(draft.missing_information),
        summary=draft.summary,
        missing_information=draft.missing_information,
        timeline=[
            CaseTimelineEvent(
                date=item.date,
                event=item.event,
                parties=item.parties,
                source_refs=resolve_source_refs(item.paragraph_ids, segments),
            )
            for item in draft.timeline
        ],
        key_facts=[_finding(item, segments) for item in draft.key_facts],
        conflicts=[_finding(item, segments) for item in draft.conflicts],
    )


def _deadline_result(
    draft: AgentDeadlineScanDraft, segments: tuple[CaseEvidenceSegment, ...]
) -> DeadlineStageResult:
    return DeadlineStageResult(
        stage="deadline_management",
        status=_status(draft.missing_information),
        summary=draft.summary,
        missing_information=draft.missing_information,
        deadlines=[
            CaseDeadline(
                name=item.name,
                trigger_date=item.trigger_date,
                deadline=item.deadline,
                uncertainty=item.uncertainty,
                source_refs=resolve_source_refs(item.paragraph_ids, segments),
            )
            for item in draft.deadlines
        ],
    )


def _evidence_result(
    draft: AgentEvidenceDraft, segments: tuple[CaseEvidenceSegment, ...]
) -> EvidenceStageResult:
    return EvidenceStageResult(
        stage="evidence_review",
        status=_status(draft.missing_information),
        summary=draft.summary,
        missing_information=draft.missing_information,
        evidence_clues=[_finding(item, segments) for item in draft.evidence_clues],
        gaps=[_finding(item, segments) for item in draft.gaps],
        reinforcement_plan=draft.reinforcement_plan,
    )


def _legal_result(
    draft: AgentLegalClassificationDraft,
    segments: tuple[CaseEvidenceSegment, ...],
) -> LegalStageResult:
    return LegalStageResult(
        stage="legal_classification",
        status=_status(draft.missing_information),
        summary=draft.summary,
        missing_information=draft.missing_information,
        legal_relations=[
            CaseLegalRelation(
                name=item.name,
                description=item.description,
                source_refs=resolve_source_refs(item.paragraph_ids, segments),
            )
            for item in draft.legal_relations
        ],
        candidate_causes=[
            CaseCandidateCause(
                name=item.name,
                reason=item.reason,
                source_refs=resolve_source_refs(item.paragraph_ids, segments),
            )
            for item in draft.candidate_causes
        ],
        procedure_questions=draft.procedure_questions,
    )


def _issue_result(
    draft: AgentIssueAnalysisDraft, segments: tuple[CaseEvidenceSegment, ...]
) -> CaseIssueAnalysis:
    return CaseIssueAnalysis(
        issue_id=draft.issue_id,
        title=draft.title,
        analysis=draft.analysis,
        positions=draft.positions,
        uncertainties=draft.uncertainties,
        missing_information=draft.missing_information,
        source_refs=resolve_source_refs(draft.paragraph_ids, segments),
    )


def _document_form_result(
    draft: AgentCaseDocumentFormDraft,
    segments: tuple[CaseEvidenceSegment, ...],
) -> CaseDocumentForm:
    """把模型段落号解析为可信引用，未知编号会使关键文书节点整体失败。"""

    return CaseDocumentForm(
        report_title=draft.report_title,
        case_summary=draft.case_summary,
        strategies=draft.strategies,
        draft_title=draft.draft_title,
        draft_purpose=draft.draft_purpose,
        key_facts=[
            CaseDocumentFact(
                text=item.text,
                source_refs=resolve_source_refs(item.paragraph_ids, segments),
            )
            for item in draft.key_facts
        ],
        core_positions_or_requests=draft.core_positions_or_requests,
        recommended_actions=draft.recommended_actions,
        missing_information=draft.missing_information,
        lawyer_review_items=draft.lawyer_review_items,
    )


def _stage_error(code: str, exc: Exception) -> CaseStageError:
    # 对外只暴露稳定错误语义，不泄露 provider 响应或案件材料。
    return CaseStageError(code=code, message=f"节点执行失败（{exc.__class__.__name__}）。")


def _failed_intake(exc: Exception) -> IntakeStageResult:
    return IntakeStageResult(
        stage="intake_screening",
        status="failed",
        summary="接案初筛未完成。",
        missing_information=[],
        error=_stage_error("intake_screening_failed", exc),
        parties=[],
        claims=[],
        case_route=None,
        red_flags=[],
    )


def _failed_deadline(exc: Exception) -> DeadlineStageResult:
    return DeadlineStageResult(
        stage="deadline_management",
        status="failed",
        summary="期限线索扫描未完成。",
        missing_information=[],
        error=_stage_error("deadline_scan_failed", exc),
        deadlines=[],
    )


def _failed_evidence(exc: Exception) -> EvidenceStageResult:
    return EvidenceStageResult(
        stage="evidence_review",
        status="failed",
        summary="证据线索审查未完成。",
        missing_information=[],
        error=_stage_error("evidence_review_failed", exc),
        evidence_clues=[],
        gaps=[],
        reinforcement_plan=[],
    )


def _dynamic_branch_summary(
    *,
    completed: int,
    expected: int,
    failures: int,
    completed_label: str,
) -> str:
    # 动态分支只按真实结果计数；失败或静默缺失时，降级文案不得声称全量完成。
    missing = max(expected - completed - failures, 0)
    parts = [f"已完成 {completed}/{expected} {completed_label}"]
    if failures:
        parts.append(f"{failures} 个分支执行失败")
    if missing:
        parts.append(f"{missing} 个分支未返回结果")
    return "，".join(parts) + "。"


def _build_response(state: CaseAnalysisGraphState) -> CaseAnalysisResponse:
    issue_results = state.get("issue_results", [])
    issue_failures = state.get("issue_failures", [])
    # 争点识别阶段的缺失信息是深度分析前置条件，必须和各争点缺失项一起汇总。
    issue_missing = _unique(
        list(state.get("issue_identification_missing", []))
        + [item for issue in issue_results for item in issue.missing_information]
    )
    deep_stage = DeepAnalysisStageResult(
        stage="deep_analysis",
        status=("failed" if issue_failures else _status(issue_missing)),
        summary=f"已围绕 {len(issue_results)} 个争议焦点形成中立、条件化分析。",
        missing_information=issue_missing,
        error=issue_failures[0] if issue_failures else None,
        issues=issue_results,
    )

    risk_results = state.get("risk_results", [])
    risk_failures = state.get("risk_failures", [])
    risk_missing = _unique(
        item for branch in risk_results for item in branch.missing_information
    )
    risk_items = [item for branch in risk_results for item in branch.risks]
    risk_level = _overall_risk([branch.risk_level for branch in risk_results])
    risk_stage = RiskStageResult(
        stage="risk_assessment",
        status=("failed" if risk_failures else _status(risk_missing)),
        summary=_dynamic_branch_summary(
            completed=len({branch.dimension for branch in risk_results}),
            expected=len(_RISK_DIMENSIONS),
            failures=len(risk_failures),
            completed_label="个风险维度",
        ),
        missing_information=risk_missing,
        error=risk_failures[0] if risk_failures else None,
        overall_risk_level=risk_level,
        risks=risk_items,
    )

    strategies = sorted(
        state.get("strategy_results", []),
        key=lambda item: _STRATEGY_MODES.index(item.mode),
    )
    strategy_failures = state.get("strategy_failures", [])
    strategy_missing = _unique(
        item for strategy in strategies for item in strategy.missing_information
    )
    strategy_error = strategy_failures[0] if strategy_failures else None
    strategy_summary = (
        "风险评估未返回有效结果，策略阶段未执行。"
        if strategy_error is not None
        and strategy_error.code == "strategy_prerequisite_failed"
        else _dynamic_branch_summary(
            completed=len({strategy.mode for strategy in strategies}),
            expected=len(_STRATEGY_MODES),
            failures=len(strategy_failures),
            completed_label="种条件化策略",
        )
    )
    strategy_stage = StrategyStageResult(
        stage="strategy_options",
        status=("failed" if strategy_failures else _status(strategy_missing)),
        summary=strategy_summary,
        missing_information=strategy_missing,
        error=strategy_error,
        strategies=strategies,
    )

    preliminary_stages = [
        state["intake_result"],
        state["fact_result"],
        state["evidence_result"],
        state["legal_result"],
        deep_stage,
        risk_stage,
        strategy_stage,
    ]
    document_form = state["document_form"]
    document_missing = _unique(
        item for stage in preliminary_stages for item in stage.missing_information
    )
    document_missing = _unique(
        [*document_missing, *document_form.missing_information]
    )
    if any(stage.status != "succeeded" for stage in preliminary_stages):
        document_missing.append("相关阶段仍需补充材料或人工复核")
        document_missing = _unique(document_missing)
    document_stage = DocumentDraftStageResult(
        stage="document_draft",
        status=_status(document_missing),
        summary="已按验证后的阶段结果生成案件分析报告草稿，不是可直接提交法院的文书。",
        missing_information=document_missing,
        draft_title=document_form.draft_title,
        draft_sections=[
            document_form.draft_purpose,
            *document_form.core_positions_or_requests,
            *document_form.recommended_actions,
        ],
        quality_checks=[
            "事实引用仅来自已上传材料段落",
            "未生成无来源法条或类案",
            "所有结论等待专业法律人士复核",
        ],
        document_form=document_form,
    )

    stages = [
        state["intake_result"],
        state["fact_result"],
        state["evidence_result"],
        state["legal_result"],
        deep_stage,
        risk_stage,
        strategy_stage,
        document_stage,
        state["deadline_result"],
    ]
    failed_stages: list[CaseStageCode] = [
        stage.stage for stage in stages if stage.status == "failed"
    ]
    limitations = _unique(
        ["首版未接入外部法条、司法解释和类案检索。"]
        + [item for stage in stages for item in stage.missing_information]
        + [f"{stage.stage} 阶段未完成。" for stage in stages if stage.status == "failed"]
    )
    findings = _unique(
        [item.title for item in issue_results] + [item.title for item in risk_items]
    )
    balanced = next((item for item in strategies if item.mode == "balanced"), None)
    suggestions = (
        balanced.steps
        if balanced is not None
        else state["evidence_result"].reinforcement_plan
    )
    summary = (
        f"{state['fact_result'].summary} 已识别 {len(issue_results)} 个争议焦点，"
        "当前结论为中立、条件化分析。"
    )
    report = CaseAnalysisReport(
        executive_summary=summary,
        overall_risk_level=risk_level,
        key_findings=findings,
        recommended_actions=suggestions,
        limitations=limitations,
        failed_stages=failed_stages,
    )
    return CaseAnalysisResponse(
        analysis_id=state["analysis_id"],
        status=("partial" if any(stage.status != "succeeded" for stage in stages) else "complete"),
        summary=summary,
        risk_level=risk_level,
        findings=findings,
        suggestions=suggestions,
        stages=stages,
        report=report,
        disclaimer=CASE_ANALYSIS_DISCLAIMER,
    )


def _overall_risk(levels: list[RiskLevel]) -> RiskLevel:
    for candidate in ("high", "medium", "low", "unknown"):
        if candidate in levels:
            return candidate  # type: ignore[return-value]
    return "unknown"


def _unique(values: Any) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
