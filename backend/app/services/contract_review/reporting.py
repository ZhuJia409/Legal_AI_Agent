import logging
from collections.abc import Sequence

from app.integrations.llm.client import LLMClientError
from app.schemas.contract_review import (
    AgentFindingDraft,
    BranchAgentDraft,
    ReportAgentDraft,
    ReviewFinding,
    ReviewModule,
    ReviewModuleError,
    ReviewModuleResult,
)
from app.schemas.contract_review.background import SourceRef
from app.services.contract_review.types import EvidenceSegment

logger = logging.getLogger("legal_ai.services.contract_review.reporting")


def _resolve_refs(
    paragraph_ids: Sequence[str],
    segments: Sequence[EvidenceSegment],
) -> list[SourceRef]:
    by_id = {item.paragraph_id: item for item in segments}
    refs: list[SourceRef] = []
    for paragraph_id in dict.fromkeys(paragraph_ids):
        segment = by_id.get(paragraph_id)
        if segment is None:
            raise ValueError(f"Unknown source reference paragraph_id: {paragraph_id}")
        refs.append(
            SourceRef(
                paragraph_id=segment.paragraph_id,
                document_name=segment.document_name,
                clause_path=segment.clause_path,
                quote=segment.text,
            )
        )
    return refs


def _module_result(
    module: ReviewModule,
    draft: BranchAgentDraft,
    segments: Sequence[EvidenceSegment],
) -> ReviewModuleResult:
    findings = [
        _finding_from_draft(module, item, index, segments)
        for index, item in enumerate(draft.findings, start=1)
    ]
    return ReviewModuleResult(
        module=module,
        status="succeeded",
        summary=draft.summary,
        findings=findings,
        missing_evidence=draft.missing_evidence,
    )


def _finding_from_draft(
    module: ReviewModule,
    draft: AgentFindingDraft,
    index: int,
    segments: Sequence[EvidenceSegment],
) -> ReviewFinding:
    finding_id = f"{module}-{index:03d}"
    return ReviewFinding(
        finding_id=finding_id,
        module=module,
        risk_level=draft.risk_level,
        contract_location=draft.contract_location,
        issue=draft.issue,
        basis=draft.basis,
        impact=draft.impact,
        suggestion=draft.suggestion,
        negotiation_strategy=draft.negotiation_strategy,
        source_refs=_resolve_refs(draft.paragraph_ids, segments),
        source_finding_ids=[finding_id],
        requires_human_review=True,
    )


def _failed_module(module: ReviewModule, exc: Exception) -> ReviewModuleResult:
    logger.warning(
        "contract_review_branch_failed module=%s error_type=%s",
        module,
        exc.__class__.__name__,
    )
    return ReviewModuleResult(
        module=module,
        status="failed",
        summary="该审查模块暂时不可用。",
        error=ReviewModuleError(
            code="module_execution_failed",
            message="模型未能返回有效的结构化审查结果。",
        ),
    )


def _consolidate_findings(
    draft: ReportAgentDraft,
    source_findings: Sequence[ReviewFinding],
) -> list[ReviewFinding]:
    source_by_id = {item.finding_id: item for item in source_findings}
    consolidated: list[ReviewFinding] = []
    covered: set[str] = set()
    rank = {"fatal": 0, "high": 1, "medium": 2, "low": 3}

    for item in draft.findings:
        selected_ids: set[str] = set()
        if len(set(item.source_finding_ids)) != len(item.source_finding_ids):
            raise LLMClientError("Report reused finding_id within one group")
        for finding_id in item.source_finding_ids:
            if finding_id in covered:
                raise LLMClientError(f"Report reused finding_id: {finding_id}")
            source = source_by_id.get(finding_id)
            if source is None:
                raise LLMClientError(f"Report referenced unknown finding_id: {finding_id}")
            covered.add(finding_id)
            selected_ids.add(finding_id)
        # 合并内容只从原 finding 确定性派生，报告模型无权改写事实或法律风险。
        sources = [item for item in source_findings if item.finding_id in selected_ids]
        refs: list[SourceRef] = []
        seen_refs: set[tuple[str, str | None]] = set()
        for source in sources:
            for ref in source.source_refs:
                key = (ref.paragraph_id, ref.document_name)
                if key not in seen_refs:
                    seen_refs.add(key)
                    refs.append(ref)
        consolidated.append(
            ReviewFinding(
                finding_id=sources[0].finding_id,
                module=sources[0].module,
                risk_level=min(sources, key=lambda source: rank[source.risk_level]).risk_level,
                contract_location=_join_source_text(
                    [source.contract_location for source in sources]
                ),
                issue=_join_source_text([source.issue for source in sources]),
                basis=_join_source_text([source.basis for source in sources]),
                impact=_join_source_text([source.impact for source in sources]),
                suggestion=_join_source_text([source.suggestion for source in sources]),
                negotiation_strategy=_join_source_text(
                    [source.negotiation_strategy for source in sources]
                ),
                source_refs=refs,
                source_finding_ids=[source.finding_id for source in sources],
                requires_human_review=True,
            )
        )

    consolidated.extend(item for item in source_findings if item.finding_id not in covered)
    return sorted(consolidated, key=lambda item: rank[item.risk_level])


def _join_source_text(values: Sequence[str]) -> str:
    unique = list(dict.fromkeys(value.strip() for value in values if value.strip()))
    return "；".join(
        value.rstrip("；;。") if index < len(unique) - 1 else value
        for index, value in enumerate(unique)
    )
