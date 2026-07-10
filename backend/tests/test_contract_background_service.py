from typing import Any

import pytest

from app.integrations.llm.client import LLMClientError
from app.services.contract_background import ContractBackgroundService


class StubBackgroundAgentRunner:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.title: str | None = None
        self.content = ""

    async def analyze(self, *, title: str | None, content: str) -> dict[str, Any]:
        self.title = title
        self.content = content
        return self.payload


def _valid_payload() -> dict[str, Any]:
    return {
        "summary": "This draft appears to be a software service agreement.",
        "contract_category": "technology_data_ip",
        "background_card": {
            "commercial_purpose": "Purchase SaaS platform services.",
            "party_position": "Client-side position can be inferred from payment clauses.",
            "counterparty_identity": "Vendor is described as a software service provider.",
            "amount_term_scope": "Annual service term; amount not stated.",
            "business_focus": "Data security and service availability.",
            "urgency_deadline": None,
        },
        "related_documents": [
            {
                "name": "SOW / requirements document",
                "status": "missing",
                "reason": "The contract references service scope but no SOW is included.",
            }
        ],
        "missing_questions": [
            "What is the signing deadline?",
            "What contract amount or pricing schedule applies?",
        ],
        "pitfalls": [
            {
                "name": "Name-substance mismatch",
                "risk": "The title says cooperation, but clauses impose SaaS service obligations.",
                "review_action": "Classify by obligations rather than title alone.",
            }
        ],
    }


@pytest.mark.asyncio
async def test_contract_background_service_returns_phase0_response() -> None:
    runner = StubBackgroundAgentRunner(_valid_payload())

    result = await ContractBackgroundService(runner).analyze(
        title="Software Service Agreement",
        content="Client purchases SaaS platform services from Vendor.",
    )

    assert runner.title == "Software Service Agreement"
    assert "SaaS platform" in runner.content
    assert result.module == "contract_background"
    assert result.contract_category == "technology_data_ip"
    assert result.background_card.commercial_purpose == "Purchase SaaS platform services."
    assert result.background_card.urgency_deadline is None
    assert result.related_documents[0].status == "missing"
    assert result.missing_questions == [
        "What is the signing deadline?",
        "What contract amount or pricing schedule applies?",
    ]
    assert result.pitfalls[0].name == "Name-substance mismatch"
    assert "professional legal" in result.disclaimer.lower()


@pytest.mark.asyncio
async def test_contract_background_service_rejects_invalid_agent_output() -> None:
    runner = StubBackgroundAgentRunner(
        {
            **_valid_payload(),
            "contract_category": "unsupported_category",
        }
    )

    with pytest.raises(LLMClientError, match="structured contract background"):
        await ContractBackgroundService(runner).analyze(
            title=None,
            content="Short contract text.",
        )
