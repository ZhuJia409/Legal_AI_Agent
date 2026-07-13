from app.integrations.llm.client import LLMClientProtocol
from app.schemas.analysis import AnalysisResponse
from app.services.analysis_common import LEGAL_ANALYSIS_SYSTEM_PROMPT, build_analysis_response


class CaseAnalysisService:
    def __init__(self, llm_client: LLMClientProtocol) -> None:
        self.llm_client = llm_client

    async def analyze(self, *, title: str | None, content: str) -> AnalysisResponse:
        payload = await self.llm_client.complete_json(
            system_prompt=LEGAL_ANALYSIS_SYSTEM_PROMPT,
            user_prompt=build_case_analysis_prompt(title, content),
        )
        return build_analysis_response("case_analysis", payload)


def build_case_analysis_prompt(title: str | None, content: str) -> str:
    case_title = title or "未命名案件"
    return f"""
请对以下案件材料进行结构化案件分析。

案件标题：
{case_title}

案件材料：
{content}

请重点覆盖：
1. 案情摘要：用简洁语言概括基本事实。
2. 争议焦点：列出双方可能争议的核心问题。
3. 关键事实：识别影响法律判断的事实。
4. 证据：梳理已出现的证据线索和仍需补充的证据。
5. 法律风险：判断风险等级，并说明主要风险来源。
6. 下一步建议：给出可执行的处理建议。

只返回 JSON 对象，格式如下：
{{
  "summary": "案情摘要",
  "risk_level": "low | medium | high",
  "findings": ["争议焦点、关键事实、证据或风险发现"],
  "suggestions": ["下一步建议"]
}}
""".strip()
