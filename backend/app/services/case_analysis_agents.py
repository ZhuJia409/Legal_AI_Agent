"""案件分析节点共用的 LangChain 结构化 Agent 运行器。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx
from langchain.agents import create_agent
from langchain.agents.structured_output import StructuredOutputError
from langchain_openai import ChatOpenAI
from openai import OpenAIError
from pydantic import BaseModel, ValidationError

from app.integrations.llm.client import LLMClientError, LLMConfigurationError

logger = logging.getLogger("legal_ai.services.case_analysis_agents")


class CaseAnalysisStructuredOutputError(LLMClientError):
    """所有候选模型均未返回符合案件节点 schema 的结构化结果。"""


class CaseAnalysisModelInvocationError(LLMClientError):
    """模型服务网络或 provider 调用失败，可安全尝试备用模型。"""


@dataclass(frozen=True, slots=True)
class CaseAgentRunResult:
    output: BaseModel


class CaseAnalysisAgentRunnerProtocol(Protocol):
    async def run(
        self,
        *,
        module: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        analysis_id: str,
    ) -> CaseAgentRunResult:
        """执行一个严格结构化的案件分析节点。"""


class StructuredInvokerProtocol(Protocol):
    async def __call__(
        self,
        *,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        module: str,
        analysis_id: str,
    ) -> BaseModel:
        """调用单个模型并返回已经解析的结构化对象。"""


class LangChainCaseAnalysisAgentRunner:
    """限制并发，并按主模型、备用模型顺序运行官方 create_agent。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        fallback_model: str | None,
        max_concurrency: int = 4,
        timeout_seconds: float = 120,
        invoke_structured: StructuredInvokerProtocol | None = None,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.fallback_model = fallback_model
        self.max_concurrency = max_concurrency
        self.timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._invoke_structured = invoke_structured or self._invoke_with_langchain

    async def run(
        self,
        *,
        module: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        analysis_id: str,
    ) -> CaseAgentRunResult:
        if not self.api_key:
            raise LLMConfigurationError("LLM_API_KEY is not configured")

        errors: list[Exception] = []
        structured_errors: list[Exception] = []
        # 信号量包住完整候选模型序列，避免备用模型重试突破全局并发上限。
        async with self._semaphore:
            for model_name in self._candidate_models():
                started = time.monotonic()
                try:
                    raw_output = await self._invoke_structured(
                        model_name=model_name,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        response_model=response_model,
                        module=module,
                        analysis_id=analysis_id,
                    )
                    output = response_model.model_validate(raw_output.model_dump())
                    logger.info(
                        "case_analysis_agent_completed analysis_id=%s module=%s model=%s "
                        "prompt_length=%d elapsed=%.2fs",
                        analysis_id,
                        module,
                        model_name,
                        len(user_prompt),
                        time.monotonic() - started,
                    )
                    return CaseAgentRunResult(output=output)
                except LLMConfigurationError:
                    raise
                except CaseAnalysisStructuredOutputError as exc:
                    errors.append(exc)
                    structured_errors.append(exc)
                    logger.warning(
                        "case_analysis_agent_failed analysis_id=%s module=%s model=%s "
                        "error_type=%s elapsed=%.2fs",
                        analysis_id,
                        module,
                        model_name,
                        exc.__class__.__name__,
                        time.monotonic() - started,
                    )
                except (ValidationError, StructuredOutputError) as exc:
                    structured_error = CaseAnalysisStructuredOutputError(
                        f"{module} returned invalid structured output"
                    )
                    errors.append(structured_error)
                    structured_errors.append(structured_error)
                    logger.warning(
                        "case_analysis_agent_failed analysis_id=%s module=%s model=%s "
                        "error_type=%s elapsed=%.2fs",
                        analysis_id,
                        module,
                        model_name,
                        exc.__class__.__name__,
                        time.monotonic() - started,
                    )
                except CaseAnalysisModelInvocationError as exc:
                    errors.append(exc)
                    logger.warning(
                        "case_analysis_agent_failed analysis_id=%s module=%s model=%s "
                        "error_type=%s elapsed=%.2fs",
                        analysis_id,
                        module,
                        model_name,
                        exc.__class__.__name__,
                        time.monotonic() - started,
                    )

        if structured_errors and len(structured_errors) == len(errors):
            raise CaseAnalysisStructuredOutputError(
                f"{module} failed structured output for all configured models"
            ) from errors[-1]
        raise LLMClientError(f"{module} failed for all configured models") from errors[-1]

    async def _invoke_with_langchain(
        self,
        *,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        module: str,
        analysis_id: str,
    ) -> BaseModel:
        model = ChatOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            model=model_name,
            temperature=0,
            timeout=self.timeout_seconds,
            max_retries=1,
            extra_body={"enable_thinking": False},
        )
        agent = create_agent(
            model=model,
            tools=[],
            system_prompt=system_prompt,
            response_format=response_model,
        )
        try:
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_prompt}]},
                config={
                    "recursion_limit": 8,
                    "run_name": f"case_analysis_{module}",
                    "tags": [
                        "legal-ai-agent",
                        "case-analysis",
                        module,
                        f"model:{model_name}",
                    ],
                    "metadata": {
                        "analysis_id": analysis_id,
                        "module": module,
                        "model": model_name,
                        "prompt_length": len(user_prompt),
                    },
                },
            )
        except StructuredOutputError:
            raise
        except (OpenAIError, httpx.HTTPError, TimeoutError) as exc:
            raise CaseAnalysisModelInvocationError(
                f"{module} model invocation failed"
            ) from exc
        structured = result.get("structured_response")
        if isinstance(structured, response_model):
            return structured
        if isinstance(structured, dict):
            return response_model.model_validate(structured)
        raise CaseAnalysisStructuredOutputError(
            f"{module} did not return structured output"
        )

    def _candidate_models(self) -> Sequence[str]:
        if self.fallback_model and self.fallback_model != self.model:
            return (self.model, self.fallback_model)
        return (self.model,)
