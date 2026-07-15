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
    AgentCaseDocumentFormDraft,
    AgentDeadlineScanDraft,
    AgentEvidenceDraft,
    AgentFactDraft,
    AgentIntakeDraft,
    AgentIssueAnalysisDraft,
    AgentIssueIdentificationDraft,
    AgentIssueSpecDraft,
    AgentLegalClassificationDraft,
    AgentRiskDraft,
    AgentStrategyDraft,
    CaseAnalysisResponse,
    CaseDocumentForm,
    CaseIssueAnalysis,
    CaseRiskItem,
    CaseStageError,
    CaseStrategy,
    DeadlineStageResult,
    EvidenceStageResult,
    FactStageResult,
    IntakeStageResult,
    LegalStageResult,
    RiskLevel,
)
from app.services.case_analysis.agents import (
    CaseAnalysisAgentRunnerProtocol,
    CaseAnalysisStructuredOutputError,
)
from app.services.case_analysis.constants import _RISK_DIMENSIONS, _STRATEGY_MODES
from app.services.case_analysis.evidence import (
    CaseEvidenceSegment,
    UnknownCaseSourceError,
    format_case_evidence,
    resolve_source_refs,
    segment_case_material,
)
from app.services.case_analysis.results import (
    _build_response,
    _deadline_result,
    _document_form_result,
    _evidence_result,
    _fact_result,
    _failed_deadline,
    _failed_evidence,
    _failed_intake,
    _intake_result,
    _issue_result,
    _legal_result,
    _stage_error,
)

_SYSTEM_PROMPT = """
你是严谨的中国法律案件材料分析助手。你只能依据用户提供的编号材料段落工作，不得补造
事实、证据、法条、案例、客户立场或程序日期。首版未接入外部法律检索，因此不得声称已
核验现行法或类案。所有结论都必须是中立、条件化且等待专业法律人士复核的分析草稿。
不得输出精确胜诉概率、任何胜诉百分比或其他伪精确的案件结果预测。
引用只能返回材料中真实存在的 paragraph_id，不要复制原文，不要输出 Markdown。
""".strip()

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
