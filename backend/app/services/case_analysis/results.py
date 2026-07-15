from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from app.schemas.case_analysis import (
    CASE_ANALYSIS_DISCLAIMER,
    AgentCaseDocumentFormDraft,
    AgentDeadlineScanDraft,
    AgentEvidenceDraft,
    AgentFactDraft,
    AgentFindingDraft,
    AgentIntakeDraft,
    AgentIssueAnalysisDraft,
    AgentLegalClassificationDraft,
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
    CaseStageCode,
    CaseStageError,
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
from app.services.case_analysis.constants import _RISK_DIMENSIONS, _STRATEGY_MODES
from app.services.case_analysis.evidence import CaseEvidenceSegment, resolve_source_refs

if TYPE_CHECKING:
    from app.services.case_analysis.graph import CaseAnalysisGraphState


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
