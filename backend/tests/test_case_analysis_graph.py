from __future__ import annotations

import asyncio
import logging

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas.case_analysis import (
    AgentCandidateCauseDraft,
    AgentClaimDraft,
    AgentDeadlineDraft,
    AgentDeadlineScanDraft,
    AgentEvidenceDraft,
    AgentFactDraft,
    AgentFindingDraft,
    AgentIntakeDraft,
    AgentIssueAnalysisDraft,
    AgentIssueIdentificationDraft,
    AgentIssueSpecDraft,
    AgentLegalClassificationDraft,
    AgentLegalRelationDraft,
    AgentPartyDraft,
    AgentRiskDraft,
    AgentRiskItemDraft,
    AgentStrategyDraft,
    AgentTimelineEventDraft,
    CaseStageCode,
)
from app.services.case_analysis_agents import (
    CaseAgentRunResult,
    CaseAnalysisModelInvocationError,
    CaseAnalysisStructuredOutputError,
    LangChainCaseAnalysisAgentRunner,
)
from app.services.case_analysis_graph import (
    _SYSTEM_PROMPT,
    CaseAnalysisCriticalStageError,
    CaseAnalysisGraphService,
)

STAGE_ORDER: list[CaseStageCode] = [
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


def test_deadline_without_trigger_date_rejects_computed_deadline() -> None:
    with pytest.raises(ValidationError):
        AgentDeadlineDraft(
            name="上诉期限",
            trigger_date=None,
            deadline="2026-07-31",
            uncertainty="缺少裁判文书送达日期。",
            paragraph_ids=["p0001"],
        )


@pytest.mark.parametrize("trigger_date", ["", "   "], ids=["empty", "whitespace"])
def test_blank_trigger_date_rejects_computed_deadline(trigger_date: str) -> None:
    with pytest.raises(ValidationError):
        AgentDeadlineDraft(
            name="上诉期限",
            trigger_date=trigger_date,
            deadline="2026-07-31",
            uncertainty="以实际送达日期为准",
            paragraph_ids=["p0001"],
        )


def test_non_blank_trigger_date_accepts_computed_deadline() -> None:
    draft = AgentDeadlineDraft(
        name="上诉期限",
        trigger_date="2026-07-01",
        deadline="2026-07-31",
        uncertainty="以实际送达日期为准",
        paragraph_ids=["p0001"],
    )

    assert draft.trigger_date == "2026-07-01"
    assert draft.deadline == "2026-07-31"


@pytest.mark.parametrize(
    "draft_factory",
    [
        lambda: AgentIssueSpecDraft(
            issue_id="unsafe-model-id",
            title="争议焦点",
            question="款项性质如何认定？",
            paragraph_ids=[],
        ),
        lambda: AgentIssueAnalysisDraft(
            issue_id="issue-01",
            title="争议焦点分析",
            analysis="现有材料不足以形成确定结论。",
            positions=[],
            uncertainties=[],
            paragraph_ids=[],
            missing_information=[],
        ),
    ],
    ids=["issue_spec", "issue_analysis"],
)
def test_issue_drafts_require_at_least_one_source_paragraph(draft_factory) -> None:  # noqa: ANN001
    with pytest.raises(ValidationError):
        draft_factory()


def test_case_analysis_system_prompt_forbids_exact_win_probability() -> None:
    assert "不得输出精确胜诉概率" in _SYSTEM_PROMPT
    assert "百分比" in _SYSTEM_PROMPT


class FakeCaseRunner:
    def __init__(
        self,
        *,
        fail_modules: set[str] | None = None,
        synchronize_first_wave: bool = False,
        draft_overrides: dict[str, BaseModel] | None = None,
    ) -> None:
        self.fail_modules = fail_modules or set()
        self.calls: list[str] = []
        self.first_wave_entered: set[str] = set()
        self.first_wave_ready = asyncio.Event()
        self.synchronize_first_wave = synchronize_first_wave
        self.draft_overrides = draft_overrides or {}

    async def run(
        self,
        *,
        module: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        analysis_id: str,
    ) -> CaseAgentRunResult:
        del system_prompt, user_prompt, response_model, analysis_id
        self.calls.append(module)
        if module in self.fail_modules:
            raise CaseAnalysisModelInvocationError(f"forced failure: {module}")
        if self.synchronize_first_wave and module in {
            "intake_screening",
            "fact_reconstruction",
            "deadline_scan",
        }:
            self.first_wave_entered.add(module)
            if len(self.first_wave_entered) == 3:
                self.first_wave_ready.set()
            await asyncio.wait_for(self.first_wave_ready.wait(), timeout=1)
        if module in self.draft_overrides:
            return CaseAgentRunResult(output=self.draft_overrides[module])
        return CaseAgentRunResult(output=_draft_for(module))


def _finding(title: str) -> AgentFindingDraft:
    return AgentFindingDraft(title=title, detail=f"{title}详情", paragraph_ids=["p0002"])


def _draft_for(module: str) -> BaseModel:
    if module == "intake_screening":
        return AgentIntakeDraft(
            summary="已识别双方和表面诉求，但未明确委托方。",
            parties=[AgentPartyDraft(name="刘某", role="原告", paragraph_ids=["p0001"])],
            claims=[
                AgentClaimDraft(
                    claimant="刘某",
                    request="返还彩礼及其他给付",
                    paragraph_ids=["p0002"],
                )
            ],
            case_route="婚姻家事/婚约财产纠纷",
            red_flags=[_finding("代理立场未明确")],
            missing_information=["委托代理刘某还是赵某"],
        )
    if module == "fact_reconstruction":
        return AgentFactDraft(
            summary="已重构订婚、转账、婚礼、生育和拒绝登记的时间线。",
            timeline=[
                AgentTimelineEventDraft(
                    date="2019年12月30日",
                    event="刘某一方向赵某转账131400元",
                    parties=["刘某", "赵某"],
                    paragraph_ids=["p0002"],
                )
            ],
            key_facts=[_finding("双方未办理结婚登记")],
            conflicts=[_finding("131400元性质存在争议")],
            missing_information=[],
        )
    if module == "deadline_scan":
        return AgentDeadlineScanDraft(
            summary="材料没有送达、立案或举证通知日期，不能计算程序期限。",
            deadlines=[
                AgentDeadlineDraft(
                    name="程序期限待确认",
                    trigger_date=None,
                    deadline=None,
                    uncertainty="缺少触发日期和程序阶段",
                    paragraph_ids=[],
                )
            ],
            missing_information=["起诉或送达日期", "举证通知书"],
        )
    if module == "evidence_review":
        return AgentEvidenceDraft(
            summary="材料仅描述证据线索，不能终判证据三性。",
            evidence_clues=[_finding("转账记录线索")],
            gaps=[_finding("缺少银行流水和聊天记录")],
            reinforcement_plan=["补充转账凭证", "补充订婚及给付目的沟通记录"],
            missing_information=["原始转账凭证"],
        )
    if module == "legal_classification":
        return AgentLegalClassificationDraft(
            summary="存在婚约财产与赠与关系候选。",
            legal_relations=[
                AgentLegalRelationDraft(
                    name="婚约财产关系",
                    description="围绕结婚目的给付财物产生争议。",
                    paragraph_ids=["p0002"],
                )
            ],
            candidate_causes=[
                AgentCandidateCauseDraft(
                    name="婚约财产纠纷",
                    reason="材料明确记载订婚、给付及未登记结婚。",
                    paragraph_ids=["p0001", "p0002"],
                )
            ],
            procedure_questions=["需由律师核对管辖与程序阶段"],
            missing_information=[],
        )
    if module == "identify_issues":
        return AgentIssueIdentificationDraft(
            summary="识别六个候选争点用于验证上限。",
            issues=[
                AgentIssueSpecDraft(
                    issue_id=f"issue-{index}",
                    title=f"争议焦点{index}",
                    question=f"问题{index}",
                    paragraph_ids=["p0002"],
                )
                for index in range(1, 7)
            ],
            missing_information=[],
        )
    if module.startswith("issue_analysis:"):
        issue_id = module.split(":", 1)[1]
        return AgentIssueAnalysisDraft(
            issue_id=issue_id,
            title=f"{issue_id}分析",
            analysis="只能依据现有材料作条件化分析。",
            positions=["刘某主张为彩礼", "赵某主张为赠与"],
            uncertainties=["缺少给付目的的原始证据"],
            paragraph_ids=["p0002"],
            missing_information=[],
        )
    if module.startswith("risk:"):
        dimension = module.split(":", 1)[1]
        missing = ["对方财产线索"] if dimension == "execution_cost" else []
        return AgentRiskDraft(
            dimension=dimension,  # type: ignore[arg-type]
            summary=f"{dimension}风险分析",
            risk_level="unknown" if missing else "medium",
            risks=[
                AgentRiskItemDraft(
                    title=f"{dimension}风险",
                    detail="现有材料不足以形成确定结论。",
                    risk_level="unknown" if missing else "medium",
                    mitigation="补充材料并由律师复核。",
                    paragraph_ids=["p0002"],
                )
            ],
            missing_information=missing,
        )
    if module.startswith("strategy:"):
        mode = module.split(":", 1)[1]
        return AgentStrategyDraft(
            mode=mode,  # type: ignore[arg-type]
            summary=f"{mode}方案",
            objective="在证据补强后选择处理路径。",
            steps=["补充证据", "由律师复核法律依据"],
            prerequisites=["明确委托方立场"],
            risks=["材料不足导致方案需调整"],
            missing_information=["客户风险偏好"],
        )
    raise AssertionError(f"unexpected module: {module}")


@pytest.mark.asyncio
async def test_graph_runs_first_wave_in_parallel_and_aggregates_dynamic_workers() -> None:
    runner = FakeCaseRunner(synchronize_first_wave=True)
    service = CaseAnalysisGraphService(runner, max_issues=5)

    result = await asyncio.wait_for(
        service.analyze(title="婚约财产纠纷", content="【案件基本信息】\n\n【基本案情】"),
        timeout=3,
    )

    assert runner.first_wave_entered == {
        "intake_screening",
        "fact_reconstruction",
        "deadline_scan",
    }
    assert len([item for item in runner.calls if item.startswith("issue_analysis:")]) == 5
    assert {item.split(":", 1)[1] for item in runner.calls if item.startswith("risk:")} == {
        "internal",
        "opponent",
        "execution_cost",
    }
    assert {item.split(":", 1)[1] for item in runner.calls if item.startswith("strategy:")} == {
        "aggressive",
        "balanced",
        "conservative",
    }
    assert [stage.stage for stage in result.stages] == STAGE_ORDER
    assert len(result.stages[4].issues) == 5  # type: ignore[union-attr]
    assert result.status == "partial"
    assert "专业法律人士" in result.disclaimer


@pytest.mark.asyncio
async def test_graph_rejects_content_over_60000_characters_before_runner_call() -> None:
    runner = FakeCaseRunner()
    service = CaseAnalysisGraphService(runner)

    with pytest.raises(ValueError, match="60000"):
        await service.analyze(title=None, content="第一段\n\n" + "案" * 60_000)

    assert runner.calls == []


def test_graph_rejects_max_issues_above_five() -> None:
    with pytest.raises(ValueError, match="1 and 5"):
        CaseAnalysisGraphService(FakeCaseRunner(), max_issues=6)


@pytest.mark.asyncio
async def test_issue_identification_missing_information_marks_deep_analysis_needs_input() -> None:
    issue_draft = _draft_for("identify_issues")
    assert isinstance(issue_draft, AgentIssueIdentificationDraft)
    missing_information = ["需补充争议焦点成立所依赖的原始沟通记录"]
    runner = FakeCaseRunner(
        draft_overrides={
            "identify_issues": issue_draft.model_copy(
                update={"missing_information": missing_information}
            )
        }
    )
    service = CaseAnalysisGraphService(runner)

    result = await service.analyze(title=None, content="基本信息\n\n案件事实")

    deep_analysis = next(item for item in result.stages if item.stage == "deep_analysis")
    assert deep_analysis.status == "needs_input"
    assert deep_analysis.missing_information == missing_information


@pytest.mark.asyncio
async def test_model_issue_ids_are_rewritten_before_dynamic_workers_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    unsafe_issue_id = "110101199001011234"
    runner = FakeCaseRunner(
        draft_overrides={
            "identify_issues": AgentIssueIdentificationDraft(
                summary="识别两个争议焦点。",
                issues=[
                    AgentIssueSpecDraft(
                        issue_id=unsafe_issue_id,
                        title="款项性质",
                        question="款项属于彩礼还是赠与？",
                        paragraph_ids=["p0002"],
                    ),
                    AgentIssueSpecDraft(
                        issue_id="../../provider-controlled-id",
                        title="返还范围",
                        question="返还范围如何确定？",
                        paragraph_ids=["p0002"],
                    ),
                ],
                missing_information=[],
            )
        }
    )
    service = CaseAnalysisGraphService(runner, max_issues=2)
    caplog.set_level(logging.INFO, logger="legal_ai.services.case_analysis_graph")

    result = await service.analyze(title=None, content="基本信息\n\n案件事实")

    issue_modules = [item for item in runner.calls if item.startswith("issue_analysis:")]
    assert issue_modules == ["issue_analysis:issue-01", "issue_analysis:issue-02"]
    deep_analysis = next(item for item in result.stages if item.stage == "deep_analysis")
    assert [item["issue_id"] for item in deep_analysis.model_dump()["issues"]] == [
        "issue-01",
        "issue-02",
    ]
    assert unsafe_issue_id not in result.model_dump_json()
    assert unsafe_issue_id not in caplog.text


@pytest.mark.asyncio
async def test_no_identified_issue_is_a_structured_output_error() -> None:
    runner = FakeCaseRunner(
        draft_overrides={
            "identify_issues": AgentIssueIdentificationDraft(
                summary="未返回争议焦点。",
                issues=[],
                missing_information=[],
            )
        }
    )

    with pytest.raises(CaseAnalysisStructuredOutputError, match="identify_issues"):
        await CaseAnalysisGraphService(runner).analyze(
            title=None,
            content="基本信息\n\n案件事实",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "draft", "stage_code"),
    [
        (
            "issue_analysis:issue-01",
            AgentIssueAnalysisDraft(
                issue_id="wrong-issue-id",
                title="争议焦点分析",
                analysis="条件化分析。",
                positions=[],
                uncertainties=[],
                paragraph_ids=["p0002"],
                missing_information=[],
            ),
            "deep_analysis",
        ),
        ("risk:internal", _draft_for("risk:opponent"), "risk_assessment"),
        ("strategy:balanced", _draft_for("strategy:aggressive"), "strategy_options"),
    ],
    ids=["issue_id", "risk_dimension", "strategy_mode"],
)
async def test_worker_key_mismatch_is_reported_as_structured_output_error(
    module: str,
    draft: BaseModel,
    stage_code: CaseStageCode,
) -> None:
    service = CaseAnalysisGraphService(
        FakeCaseRunner(draft_overrides={module: draft})
    )

    result = await service.analyze(title=None, content="基本信息\n\n案件事实")

    stage = next(item for item in result.stages if item.stage == stage_code)
    assert result.status == "partial"
    assert stage.status == "failed"
    assert stage.error is not None
    assert "CaseAnalysisStructuredOutputError" in stage.error.message


@pytest.mark.asyncio
async def test_runner_value_error_is_not_silently_downgraded() -> None:
    class ProgrammingBugRunner(FakeCaseRunner):
        async def run(self, **kwargs: object) -> CaseAgentRunResult:
            if kwargs["module"] == "deadline_scan":
                raise ValueError("programming bug")
            return await super().run(**kwargs)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="programming bug"):
        await CaseAnalysisGraphService(ProgrammingBugRunner()).analyze(
            title=None,
            content="基本信息\n\n案件事实",
        )


@pytest.mark.asyncio
async def test_risk_summary_reports_success_and_failure_branch_counts() -> None:
    service = CaseAnalysisGraphService(
        FakeCaseRunner(fail_modules={"risk:opponent"})
    )

    result = await service.analyze(title=None, content="基本信息\n\n案件事实")

    risk_stage = next(item for item in result.stages if item.stage == "risk_assessment")
    assert risk_stage.status == "failed"
    assert len(risk_stage.risks) == 2
    assert "2/3" in risk_stage.summary
    assert "1 个分支执行失败" in risk_stage.summary


@pytest.mark.asyncio
async def test_all_risk_failures_skip_strategy_workers_and_mark_prerequisite_failure() -> None:
    runner = FakeCaseRunner(
        fail_modules={
            "risk:internal",
            "risk:opponent",
            "risk:execution_cost",
        }
    )
    service = CaseAnalysisGraphService(runner)

    result = await service.analyze(title=None, content="基本信息\n\n案件事实")

    risk_stage = next(item for item in result.stages if item.stage == "risk_assessment")
    strategy_stage = next(item for item in result.stages if item.stage == "strategy_options")
    assert result.status == "partial"
    assert risk_stage.status == "failed"
    assert risk_stage.risks == []
    assert not any(module.startswith("strategy:") for module in runner.calls)
    assert strategy_stage.status == "failed"
    assert strategy_stage.strategies == []
    assert strategy_stage.error is not None
    assert strategy_stage.error.code == "strategy_prerequisite_failed"
    assert strategy_stage.summary == "风险评估未返回有效结果，策略阶段未执行。"


@pytest.mark.asyncio
async def test_strategy_summary_reports_success_and_failure_branch_counts() -> None:
    service = CaseAnalysisGraphService(
        FakeCaseRunner(fail_modules={"strategy:balanced"})
    )

    result = await service.analyze(title=None, content="基本信息\n\n案件事实")

    strategy_stage = next(item for item in result.stages if item.stage == "strategy_options")
    assert strategy_stage.status == "failed"
    assert len(strategy_stage.strategies) == 2
    assert "2/3" in strategy_stage.summary
    assert "1 个分支执行失败" in strategy_stage.summary


@pytest.mark.asyncio
async def test_optional_branch_failure_returns_partial_failed_stage() -> None:
    service = CaseAnalysisGraphService(FakeCaseRunner(fail_modules={"deadline_scan"}))

    result = await service.analyze(title=None, content="基本信息\n\n案件事实")

    deadline = next(item for item in result.stages if item.stage == "deadline_management")
    assert result.status == "partial"
    assert deadline.status == "failed"
    assert deadline.error is not None


@pytest.mark.asyncio
async def test_foundation_failure_raises_controlled_exception() -> None:
    service = CaseAnalysisGraphService(
        FakeCaseRunner(fail_modules={"legal_classification"})
    )

    with pytest.raises(CaseAnalysisCriticalStageError, match="legal_classification"):
        await service.analyze(title=None, content="基本信息\n\n案件事实")


@pytest.mark.asyncio
async def test_foundation_structured_output_failure_is_preserved() -> None:
    class StructuredFailureRunner(FakeCaseRunner):
        async def run(self, **kwargs: object) -> CaseAgentRunResult:
            if kwargs["module"] == "fact_reconstruction":
                raise CaseAnalysisStructuredOutputError("invalid structured output")
            return await super().run(**kwargs)  # type: ignore[arg-type]

    service = CaseAnalysisGraphService(StructuredFailureRunner())

    with pytest.raises(CaseAnalysisStructuredOutputError):
        await service.analyze(title=None, content="基本信息\n\n案件事实")


@pytest.mark.asyncio
@pytest.mark.parametrize("bug_module", ["intake_screening", "fact_reconstruction"])
async def test_unexpected_graph_node_bug_is_not_silently_downgraded(
    bug_module: str,
) -> None:
    class ProgrammingBugRunner(FakeCaseRunner):
        async def run(self, **kwargs: object) -> CaseAgentRunResult:
            if kwargs["module"] == bug_module:
                raise TypeError("programming bug")
            return await super().run(**kwargs)  # type: ignore[arg-type]

    service = CaseAnalysisGraphService(ProgrammingBugRunner())

    with pytest.raises(TypeError, match="programming bug"):
        await service.analyze(title=None, content="基本信息\n\n案件事实")


@pytest.mark.asyncio
async def test_runner_limits_concurrency_and_falls_back_without_network() -> None:
    active = 0
    peak = 0
    calls: list[str] = []
    release = asyncio.Event()

    async def invoke(
        *,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        module: str,
        analysis_id: str,
    ) -> BaseModel:
        nonlocal active, peak
        del system_prompt, user_prompt, response_model, module, analysis_id
        calls.append(model_name)
        if model_name == "primary" and len(calls) == 1:
            raise CaseAnalysisModelInvocationError("primary unavailable")
        active += 1
        peak = max(peak, active)
        if active == 4:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=1)
        active -= 1
        return _finding("结果")

    runner = LangChainCaseAnalysisAgentRunner(
        base_url="https://example.invalid/v1",
        api_key="test-key",
        model="primary",
        fallback_model="fallback",
        max_concurrency=4,
        invoke_structured=invoke,
    )

    await asyncio.gather(
        *[
            runner.run(
                module=f"test-{index}",
                system_prompt="system",
                user_prompt="user",
                response_model=AgentFindingDraft,
                analysis_id="analysis-1",
            )
            for index in range(8)
        ]
    )

    assert peak == 4
    assert "fallback" in calls


@pytest.mark.asyncio
async def test_runner_does_not_fallback_for_unexpected_programming_error() -> None:
    calls: list[str] = []

    async def invoke(
        *,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        module: str,
        analysis_id: str,
    ) -> BaseModel:
        del system_prompt, user_prompt, response_model, module, analysis_id
        calls.append(model_name)
        raise TypeError("programming bug")

    runner = LangChainCaseAnalysisAgentRunner(
        base_url="https://example.invalid/v1",
        api_key="test-key",
        model="primary",
        fallback_model="fallback",
        invoke_structured=invoke,
    )

    with pytest.raises(TypeError, match="programming bug"):
        await runner.run(
            module="unexpected-error",
            system_prompt="system",
            user_prompt="user",
            response_model=AgentFindingDraft,
            analysis_id="analysis-bug",
        )

    assert calls == ["primary"]


@pytest.mark.asyncio
async def test_runner_reports_all_model_schema_failures_as_structured_output_error() -> None:
    class WrongDraft(BaseModel):
        unexpected: str

    calls: list[str] = []

    async def invoke(
        *,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        module: str,
        analysis_id: str,
    ) -> BaseModel:
        del system_prompt, user_prompt, response_model, module, analysis_id
        calls.append(model_name)
        return WrongDraft(unexpected="value")

    runner = LangChainCaseAnalysisAgentRunner(
        base_url="https://example.invalid/v1",
        api_key="test-key",
        model="primary",
        fallback_model="fallback",
        invoke_structured=invoke,
    )

    with pytest.raises(CaseAnalysisStructuredOutputError):
        await runner.run(
            module="structured-test",
            system_prompt="system",
            user_prompt="user",
            response_model=AgentFindingDraft,
            analysis_id="analysis-structured",
        )

    assert calls == ["primary", "fallback"]
