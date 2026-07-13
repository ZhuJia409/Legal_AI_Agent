import json
import logging
import re
import time
from collections.abc import Sequence
from typing import Any, Protocol

from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI, RateLimitError

logger = logging.getLogger("legal_ai.integrations.llm")


class LLMConfigurationError(RuntimeError):
    """Raised when the LLM integration is missing required runtime configuration."""


class LLMClientError(RuntimeError):
    """Raised when the upstream LLM provider fails or returns unusable output."""


class LLMClientProtocol(Protocol):
    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Return a JSON object generated from the supplied prompts."""


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        fallback_model: str | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.fallback_model = fallback_model

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if not self.api_key:
            raise LLMConfigurationError("LLM_API_KEY is not configured")

        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        errors: list[Exception] = []
        for model in self._candidate_models():
            started = time.monotonic()
            try:
                logger.info("llm_json_completion_started model=%s", model)
                completion = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                content = completion.choices[0].message.content
                if not content:
                    raise LLMClientError("LLM response did not include content")
                parsed = _parse_json_object(content)
                logger.info(
                    "llm_json_completion_completed model=%s output_keys=%s elapsed=%.2fs",
                    model,
                    sorted(parsed.keys()),
                    time.monotonic() - started,
                )
                return parsed
            except LLMConfigurationError:
                raise
            except (
                APIConnectionError,
                APIError,
                APITimeoutError,
                RateLimitError,
                LLMClientError,
            ) as exc:
                logger.warning(
                    "llm_json_completion_failed model=%s error_type=%s elapsed=%.2fs",
                    model,
                    exc.__class__.__name__,
                    time.monotonic() - started,
                )
                errors.append(exc)

        logger.error("llm_json_completion_exhausted models=%s", list(self._candidate_models()))
        raise LLMClientError("LLM provider failed to return a valid JSON response") from errors[-1]

    def _candidate_models(self) -> Sequence[str]:
        if self.fallback_model and self.fallback_model != self.model:
            return [self.model, self.fallback_model]
        return [self.model]


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = json.loads(_extract_json_object(content))

    if not isinstance(parsed, dict):
        raise LLMClientError("LLM response JSON must be an object")
    return parsed


def _extract_json_object(content: str) -> str:
    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fenced_match:
        return fenced_match.group(1)

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMClientError("LLM response did not contain a JSON object")
    return content[start : end + 1]
