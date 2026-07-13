from typing import Any

import pytest

from app.services.case_analysis import CaseAnalysisService, build_case_analysis_prompt


class StubLLMClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.user_prompt = ""

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self.user_prompt = user_prompt
        return self.payload


def test_case_analysis_prompt_contains_required_legal_sections() -> None:
    prompt = build_case_analysis_prompt("买卖合同纠纷", "甲方逾期交货。")

    for keyword in ["案情摘要", "争议焦点", "关键事实", "证据", "法律风险", "下一步建议"]:
        assert keyword in prompt


@pytest.mark.asyncio
async def test_case_analysis_service_normalizes_llm_result() -> None:
    llm_client = StubLLMClient(
        {
            "summary": "案情摘要",
            "risk_level": "unknown",
            "findings": "单个问题",
            "suggestions": ["建议"],
        }
    )

    result = await CaseAnalysisService(llm_client).analyze(title=None, content="案件事实")

    assert result.module == "case_analysis"
    assert result.risk_level == "medium"
    assert result.findings == ["单个问题"]
    assert result.suggestions == ["建议"]
