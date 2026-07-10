import logging
import time
from collections.abc import Sequence
from typing import Any, Protocol

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from app.integrations.llm.client import LLMClientError, LLMConfigurationError
from app.schemas.contract_background import (
    ContractBackgroundAgentOutput,
    ContractBackgroundResponse,
)

logger = logging.getLogger("legal_ai.services.contract_background")

CONTRACT_BACKGROUND_DISCLAIMER = (
    "This AI-generated result is for reference only; professional legal review is required "
    "before relying on any legal conclusion."
)

CONTRACT_BACKGROUND_SYSTEM_PROMPT = """
You are a careful Chinese legal contract review assistant working on Phase 0: contract
background review. You must only use the contract text supplied by the user and read-only text
inspection tools. Do not invent facts, do not use external knowledge as evidence, and do not
present uncertain inferences as confirmed facts.

Your task:
1. Build a background card for six basic questions:
   - commercial purpose
   - party position, such as buyer/seller or party A/party B
   - counterparty identity and relationship
   - contract amount, term, and subject matter scale
   - business-side special concerns
   - urgency and deadline
2. Classify the contract into one business review category:
   commercial_transaction, service_entrustment, construction_project, technology_data_ip,
   finance_guarantee, investment_ma, labor_hr, framework_cooperation, other_unknown.
3. Review whether these 11 related document types are provided, missing, unknown, or not
   applicable. Use ONLY these exact Chinese names for the document types:
   关联文件清单, 谈判纪要/会议记录, 邮件往来, 聊天记录, 框架协议/主合同,
   招标文件及中标通知书, 技术规格/SOW/需求文档, 历史合同, 尽职调查报告,
   项目立项/内部审批文件, 相对方公示材料/报价单.
4. Return missing questions for any background item that cannot be reliably determined.
5. Check these three pitfalls and use ONLY these exact Chinese names:
   名实不符, 意向书效力, 隐形缔约过失责任触发点.

Return concise Chinese content for all fields, and keep every claim tied to the supplied text.
""".strip()


class ContractBackgroundAgentRunnerProtocol(Protocol):
    async def analyze(self, *, title: str | None, content: str) -> dict[str, Any]:
        """Return raw structured output for a contract background review."""


class ContractBackgroundService:
    def __init__(self, runner: ContractBackgroundAgentRunnerProtocol) -> None:
        self.runner = runner

    @classmethod
    def from_llm_settings(
        cls,
        *,
        base_url: str,
        api_key: str,
        model: str,
        fallback_model: str | None,
    ) -> "ContractBackgroundService":
        return cls(
            LangChainContractBackgroundAgentRunner(
                base_url=base_url,
                api_key=api_key,
                model=model,
                fallback_model=fallback_model,
            )
        )

    async def analyze(self, *, title: str | None, content: str) -> ContractBackgroundResponse:
        raw_output = await self.runner.analyze(title=title, content=content)
        try:
            agent_output = ContractBackgroundAgentOutput.model_validate(raw_output)
        except ValidationError as exc:
            raise LLMClientError(
                "LLM returned invalid structured contract background output"
            ) from exc

        return ContractBackgroundResponse(
            module="contract_background",
            disclaimer=CONTRACT_BACKGROUND_DISCLAIMER,
            **agent_output.model_dump(),
        )


class LangChainContractBackgroundAgentRunner:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        fallback_model: str | None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.fallback_model = fallback_model

    async def analyze(self, *, title: str | None, content: str) -> dict[str, Any]:
        if not self.api_key:
            raise LLMConfigurationError("LLM_API_KEY is not configured")

        errors: list[Exception] = []
        for model_name in self._candidate_models():
            started = time.monotonic()
            try:
                logger.info(
                    "contract_background_agent_attempt_started "
                    "model=%s content_length=%d has_title=%s",
                    model_name,
                    len(content),
                    bool(title),
                )
                result = await self._run_agent(model_name=model_name, title=title, content=content)
                logger.info(
                    "contract_background_agent_attempt_completed model=%s elapsed=%.2fs",
                    model_name,
                    time.monotonic() - started,
                )
                return result
            except Exception as exc:
                logger.warning(
                    "contract_background_agent_attempt_failed model=%s error_type=%s elapsed=%.2fs",
                    model_name,
                    exc.__class__.__name__,
                    time.monotonic() - started,
                )
                errors.append(exc)

        logger.error(
            "contract_background_agent_all_attempts_failed models=%s",
            list(self._candidate_models()),
        )
        raise LLMClientError(
            "LLM provider failed to return contract background output"
        ) from errors[-1]

    def _candidate_models(self) -> Sequence[str]:
        if self.fallback_model and self.fallback_model != self.model:
            return [self.model, self.fallback_model]
        return [self.model]

    async def _run_agent(
        self, *, model_name: str, title: str | None, content: str
    ) -> dict[str, Any]:
        model = ChatOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            model=model_name,
            temperature=0.1,
            extra_body={"enable_thinking": False},
        )
        agent = create_agent(
            model=model,
            tools=_build_readonly_tools(content),
            system_prompt=CONTRACT_BACKGROUND_SYSTEM_PROMPT,
            response_format=ContractBackgroundAgentOutput,
        )
        result = await agent.ainvoke(
            {
                "messages": [
                    {"role": "user", "content": build_contract_background_prompt(title, content)}
                ]
            },
            config={
                "recursion_limit": 8,
                "run_name": "contract_background_phase0",
                "tags": [
                    "legal-ai-agent",
                    "contract-background",
                    "phase0",
                    f"model:{model_name}",
                ],
                "metadata": {
                    "module": "contract_background",
                    "phase": "phase0",
                    "model": model_name,
                    "content_length": len(content),
                    "has_title": bool(title),
                },
            },
        )
        structured_response = result.get("structured_response")
        if isinstance(structured_response, ContractBackgroundAgentOutput):
            return structured_response.model_dump()
        if isinstance(structured_response, dict):
            return structured_response
        raise LLMClientError("Agent response did not include structured contract background output")


def build_contract_background_prompt(title: str | None, content: str) -> str:
    contract_title = title or "Untitled contract"
    return f"""
Review only Phase 0 contract background for the following contract.

Contract title:
{contract_title}

Contract text:
{content}

Important rules:
- If a background fact is not in the text, set that background card field to null.
- Add a missing question for every required background fact that cannot be reliably determined.
- Do not produce a full legal risk review; this is only the background preparation module.
""".strip()


def _build_readonly_tools(content: str) -> list[Any]:
    @tool
    def find_contract_excerpt(keyword: str) -> str:
        """Find a short excerpt from the provided contract text.

        Use this only to inspect the user-provided contract text. It does not access files,
        databases, networks, or external legal sources.

        Args:
            keyword: Keyword or phrase to locate in the provided contract text.
        """
        normalized = keyword.strip()
        if not normalized:
            return content[:800]

        index = content.lower().find(normalized.lower())
        if index == -1:
            return f"No exact excerpt found for keyword: {normalized}"

        start = max(0, index - 240)
        end = min(len(content), index + len(normalized) + 240)
        return content[start:end]

    @tool
    def list_phase0_related_document_types() -> str:
        """List the fixed related document checklist for Phase 0 contract background review."""
        return (
            "关联文件清单; 谈判纪要/会议记录; 邮件往来; "
            "聊天记录; 框架协议/主合同; 招标文件及中标通知书; "
            "技术规格/SOW/需求文档; 历史合同; 尽职调查报告; "
            "项目立项/内部审批文件; 相对方公示材料/报价单"
        )

    return [find_contract_excerpt, list_phase0_related_document_types]
