"""合同完整审查的 LangGraph 并联 DAG 编排。"""

import json
import logging
from collections.abc import Sequence
from typing import Any, Protocol

from langgraph.graph import END, START, StateGraph

from app.schemas.contract_review import (
    BranchAgentDraft,
    ContractPdfDocumentForm,
    ContractReviewReport,
    ContractReviewReportResponse,
    ContractTypeSelection,
    FormStructureAgentDraft,
    ReportAgentDraft,
    ReviewModule,
    ReviewModuleError,
    ReviewModuleResult,
    ReviewPerspective,
)
from app.services.contract_review.agents import (
    _PERSPECTIVE_LABELS,
    ReviewAgentRunnerProtocol,
    _branch_prompt,
    _format_evidence,
    _pdf_document_form_prompt,
    _pdf_document_form_system_prompt,
    _report_prompt,
    _report_system_prompt,
    _resolve_pdf_document_form,
    _system_prompt,
)
from app.services.contract_review.background import ContractBackgroundAnalysis
from app.services.contract_review.evidence import ContractSegment, segment_contract_markdown
from app.services.contract_review.reporting import (
    _consolidate_findings,
    _failed_module,
    _module_result,
    _resolve_refs,
)
from app.services.contract_review.type_skills import (
    CONTRACT_TYPE_RULES,
    load_contract_type_rules,
)
from app.services.contract_review.types import (
    ContractReviewGraphAnalysis,
    ContractReviewGraphState,
    EvidenceSegment,
    ParsedRelatedDocument,
)

logger = logging.getLogger("legal_ai.services.contract_review.graph")

COMPLETE_REVIEW_DISCLAIMER = (
    "本报告由 AI 基于已上传材料生成，仅供合同审查参考；所有法律判断、修改建议和"
    "签署决策必须由法律专业人士结合完整事实与最新法律进行复核。"
)
PARTIAL_REVIEW_DISCLAIMER = (
    "本报告存在未完成的审查模块，仅可作为材料整理参考，不可作为签署依据；"
    "必须补充完成审查并由法律专业人士复核。"
)


_MODULE_LABELS: dict[ReviewModule, str] = {
    "party_qualification": "主体资格审查",
    "form_structure": "形式结构审查",
    "general_substantive": "通用实质审查",
    "related_document_comparison": "关联文件比对",
    "contract_type_special": "合同类型专项审查",
}


class ContractBackgroundServiceProtocol(Protocol):
    async def analyze_with_raw_output(
        self,
        *,
        title: str | None,
        content: str,
        provided_related_documents: Sequence[str] = (),
    ) -> ContractBackgroundAnalysis:
        """执行已有合同背景审查。"""


class ContractReviewGraphService:
    def __init__(
        self,
        background_service: ContractBackgroundServiceProtocol,
        runner: ReviewAgentRunnerProtocol,
    ) -> None:
        self.background_service = background_service
        self.runner = runner
        self.graph = self._build_graph()

    async def analyze(
        self,
        *,
        task_id: str,
        title: str | None,
        content: str,
        review_perspective: ReviewPerspective,
        related_documents: Sequence[ParsedRelatedDocument] = (),
    ) -> ContractReviewGraphAnalysis:
        state = await self.graph.ainvoke(
            {
                "task_id": task_id,
                "title": title,
                "content": content,
                "review_perspective": review_perspective,
                "related_documents": list(related_documents),
                "evidence_segments": _build_evidence_segments(content, related_documents),
                "raw_outputs": [],
            },
            config={
                "recursion_limit": 20,
                "run_name": "contract_review_parallel_dag",
                "tags": ["legal-ai-agent", "contract-review", "parallel-dag"],
                "metadata": {"task_id": task_id, "review_perspective": review_perspective},
            },
        )
        return ContractReviewGraphAnalysis(
            response=state["report_response"],
            pdf_form=state["pdf_form"],
            raw_outputs=state.get("raw_outputs", []),
        )

    def _build_graph(self):
        builder = StateGraph(ContractReviewGraphState)
        builder.add_node("background_review", self._background_review_node)
        builder.add_node("party", self._party_node)
        builder.add_node("form", self._form_node)
        builder.add_node("general", self._general_node)
        builder.add_node("related", self._related_node)
        builder.add_node("special", self._special_node)
        builder.add_node("report", self._report_node)
        builder.add_node("pdf_document_form", self._pdf_document_form_node)
        builder.add_edge(START, "background_review")
        for node in ("party", "form", "general", "related"):
            builder.add_edge("background_review", node)
        builder.add_edge("form", "special")
        builder.add_edge(["party", "general", "related", "special"], "report")
        builder.add_edge("report", "pdf_document_form")
        builder.add_edge("pdf_document_form", END)
        return builder.compile()

    async def _background_review_node(
        self,
        state: ContractReviewGraphState,
    ) -> dict[str, Any]:
        analysis = await self.background_service.analyze_with_raw_output(
            title=state.get("title"),
            content=state["content"],
            provided_related_documents=[item.filename for item in state["related_documents"]],
        )
        return {
            "background": analysis.response,
            "raw_outputs": [{"module": "contract_background", "payload": analysis.raw_output}],
        }

    async def _party_node(self, state: ContractReviewGraphState) -> dict[str, Any]:
        result, raw = await self._run_branch(state, "party_qualification")
        return {"party_result": result, "raw_outputs": raw}

    async def _general_node(self, state: ContractReviewGraphState) -> dict[str, Any]:
        result, raw = await self._run_branch(state, "general_substantive")
        return {"general_result": result, "raw_outputs": raw}

    async def _form_node(self, state: ContractReviewGraphState) -> dict[str, Any]:
        module: ReviewModule = "form_structure"
        try:
            run = await self.runner.run(
                module=module,
                system_prompt=_system_prompt(module),
                user_prompt=_branch_prompt(state, module, include_type_catalog=True),
                response_model=FormStructureAgentDraft,
                task_id=state["task_id"],
            )
            draft = FormStructureAgentDraft.model_validate(run.output.model_dump())
            types = [
                ContractTypeSelection(
                    code=item.code,
                    label=CONTRACT_TYPE_RULES[item.code].label,
                    rule_pack=f"references/{CONTRACT_TYPE_RULES[item.code].path.name}",
                    is_primary=item.is_primary,
                    reason=item.reason,
                    source_refs=_resolve_refs(item.paragraph_ids, state["evidence_segments"]),
                )
                for item in draft.contract_types
            ]
            result = _module_result(module, draft, state["evidence_segments"])
            return {
                "form_result": result,
                "contract_types": types,
                "raw_outputs": [{"module": module, "payload": run.raw_output}],
            }
        except Exception as exc:
            return {
                "form_result": _failed_module(module, exc),
                "contract_types": [],
                "raw_outputs": [],
            }

    async def _related_node(self, state: ContractReviewGraphState) -> dict[str, Any]:
        module: ReviewModule = "related_document_comparison"
        documents = state["related_documents"]
        if not documents:
            return {
                "related_result": ReviewModuleResult(
                    module=module,
                    status="skipped",
                    summary="本次未上传关联文件，未执行深度比对。",
                    missing_evidence=["可用于比对的关联文件"],
                ),
                "raw_outputs": [],
            }

        successful = [item for item in documents if item.content]
        failed_names = [item.filename for item in documents if not item.content]
        if not successful:
            return {
                "related_result": ReviewModuleResult(
                    module=module,
                    status="failed",
                    summary="关联文件均未能成功解析，无法执行深度比对。",
                    missing_evidence=failed_names,
                    error=ReviewModuleError(
                        code="related_document_parse_error",
                        message="关联文件解析失败。",
                    ),
                ),
                "raw_outputs": [],
            }

        result, raw = await self._run_branch(state, module)
        if failed_names:
            result = result.model_copy(
                update={"missing_evidence": [*result.missing_evidence, *failed_names]}
            )
        return {"related_result": result, "raw_outputs": raw}

    async def _special_node(self, state: ContractReviewGraphState) -> dict[str, Any]:
        module: ReviewModule = "contract_type_special"
        contract_types = state.get("contract_types", [])
        if not contract_types:
            return {
                "special_result": ReviewModuleResult(
                    module=module,
                    status="skipped",
                    summary="合同类型确认未完成，无法安全加载专项规则。",
                    missing_evidence=["已确认的合同类型"],
                ),
                "raw_outputs": [],
            }

        try:
            rules = load_contract_type_rules([item.code for item in contract_types])
            type_payload = [item.model_dump(mode="json") for item in contract_types]
            rules_text = "\n\n".join(
                f"## {item.label}\n规则文件：references/{item.path.name}\n{item.content}"
                for item in rules
            )
            run = await self.runner.run(
                module=module,
                system_prompt=_system_prompt(module),
                user_prompt=(
                    f"审查立场：{_PERSPECTIVE_LABELS[state['review_perspective']]}\n\n"
                    f"已确认合同类型：{json.dumps(type_payload, ensure_ascii=False)}\n\n"
                    f"专项规则包：\n{rules_text}\n\n"
                    f"合同证据：\n{_format_evidence(state['evidence_segments'])}"
                ),
                response_model=BranchAgentDraft,
                task_id=state["task_id"],
            )
            draft = BranchAgentDraft.model_validate(run.output.model_dump())
            result = _module_result(module, draft, state["evidence_segments"])
            return {
                "special_result": result,
                "raw_outputs": [{"module": module, "payload": run.raw_output}],
            }
        except Exception as exc:
            return {"special_result": _failed_module(module, exc), "raw_outputs": []}

    async def _run_branch(
        self,
        state: ContractReviewGraphState,
        module: ReviewModule,
    ) -> tuple[ReviewModuleResult, list[dict[str, Any]]]:
        try:
            run = await self.runner.run(
                module=module,
                system_prompt=_system_prompt(module),
                user_prompt=_branch_prompt(state, module),
                response_model=BranchAgentDraft,
                task_id=state["task_id"],
            )
            draft = BranchAgentDraft.model_validate(run.output.model_dump())
            return (
                _module_result(module, draft, state["evidence_segments"]),
                [{"module": module, "payload": run.raw_output}],
            )
        except Exception as exc:
            return _failed_module(module, exc), []

    async def _report_node(self, state: ContractReviewGraphState) -> dict[str, Any]:
        modules = [
            state["party_result"],
            state["form_result"],
            state["general_result"],
            state["related_result"],
            state["special_result"],
        ]
        failed_modules = [item.module for item in modules if item.status == "failed"]
        if state["special_result"].status == "skipped":
            failed_modules.append("contract_type_special")
        status = "partial" if failed_modules else "complete"
        source_findings = [finding for item in modules for finding in item.findings]

        run = await self.runner.run(
            module="report",
            system_prompt=_report_system_prompt(),
            user_prompt=_report_prompt(state, modules, source_findings, status),
            response_model=ReportAgentDraft,
            task_id=state["task_id"],
        )
        draft = ReportAgentDraft.model_validate(run.output.model_dump())
        limitations = list(draft.limitations)
        limitations.extend(
            f"{_MODULE_LABELS[item.module]}缺失证据：{evidence}"
            for item in modules
            for evidence in item.missing_evidence
        )
        limitations.extend(
            f"{item.module} 模块未完成。" for item in modules if item.status == "failed"
        )
        limitations.extend(
            f"关联文件 {item.filename} 解析失败，未纳入深度比对。"
            for item in state["related_documents"]
            if not item.content
        )
        if status == "partial":
            limitations.append("本报告为不完整报告，不可作为签署依据。")

        report = ContractReviewReport(
            executive_summary=draft.executive_summary,
            overall_risk_level=draft.overall_risk_level,
            signing_recommendation=draft.signing_recommendation,
            preconditions=draft.preconditions,
            findings=_consolidate_findings(draft, source_findings),
            limitations=list(dict.fromkeys(limitations)),
            failed_modules=list(dict.fromkeys(failed_modules)),
        )
        response = ContractReviewReportResponse(
            module="contract_review_report",
            task_id=state["task_id"],
            status=status,
            review_perspective=state["review_perspective"],
            background=state["background"],
            contract_types=state.get("contract_types", []),
            modules=modules,
            report=report,
            disclaimer=(
                PARTIAL_REVIEW_DISCLAIMER if status == "partial" else COMPLETE_REVIEW_DISCLAIMER
            ),
        )
        return {
            "report_response": response,
            "raw_outputs": [{"module": "report", "payload": run.raw_output}],
        }

    async def _pdf_document_form_node(
        self,
        state: ContractReviewGraphState,
    ) -> dict[str, Any]:
        """让独立 Agent 通过 ToolStrategy 填写精简 PDF 表单。"""

        response = state["report_response"]
        run = await self.runner.run(
            module="pdf_document_form",
            system_prompt=_pdf_document_form_system_prompt(),
            user_prompt=_pdf_document_form_prompt(response),
            response_model=ContractPdfDocumentForm,
            task_id=state["task_id"],
            force_tool_strategy=True,
        )
        draft = ContractPdfDocumentForm.model_validate(run.output.model_dump())
        form = _resolve_pdf_document_form(draft, response.report.findings)
        return {
            "pdf_form": form,
            "raw_outputs": [
                {"module": "pdf_document_form", "payload": run.raw_output}
            ],
        }


def _build_evidence_segments(
    content: str,
    related_documents: Sequence[ParsedRelatedDocument],
) -> list[EvidenceSegment]:
    segments = [
        _evidence_segment(item, None, item.paragraph_id)
        for item in segment_contract_markdown(content)
    ]
    for document_index, document in enumerate(related_documents, start=1):
        if not document.content:
            continue
        for segment in segment_contract_markdown(document.content):
            segments.append(
                _evidence_segment(
                    segment,
                    document.filename,
                    f"r{document_index:02d}-{segment.paragraph_id}",
                )
            )
    return segments


def _evidence_segment(
    segment: ContractSegment,
    document_name: str | None,
    paragraph_id: str,
) -> EvidenceSegment:
    return EvidenceSegment(
        paragraph_id=paragraph_id,
        document_name=document_name,
        clause_path=segment.clause_path,
        text=segment.text,
    )
