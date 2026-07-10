from typing import Literal

from pydantic import BaseModel, Field

ContractCategory = Literal[
    "commercial_transaction",
    "service_entrustment",
    "construction_project",
    "technology_data_ip",
    "finance_guarantee",
    "investment_ma",
    "labor_hr",
    "framework_cooperation",
    "other_unknown",
]

RelatedDocumentStatus = Literal["provided", "missing", "unknown", "not_applicable"]


class BackgroundCard(BaseModel):
    commercial_purpose: str | None = Field(
        default=None,
        description="Business purpose of the transaction, if supported by the contract text.",
    )
    party_position: str | None = Field(
        default=None,
        description="Reviewer-side position such as buyer/seller or party A/party B.",
    )
    counterparty_identity: str | None = Field(
        default=None,
        description="Counterparty identity and relationship clues from the contract text.",
    )
    amount_term_scope: str | None = Field(
        default=None,
        description="Contract amount, term, subject matter, or transaction scale.",
    )
    business_focus: str | None = Field(
        default=None,
        description="Special business concerns that are explicit in the contract text.",
    )
    urgency_deadline: str | None = Field(
        default=None,
        description="Urgency or deadline if the contract text supports it.",
    )


class RelatedDocument(BaseModel):
    name: str = Field(description="Related document type to collect or verify.")
    status: RelatedDocumentStatus = Field(
        description="Whether the document is provided, missing, unknown, or not applicable."
    )
    reason: str = Field(description="Short text-based reason for the status.")


class ReviewPitfall(BaseModel):
    name: str = Field(description="Pitfall name.")
    risk: str = Field(description="Why this pitfall may matter for the current contract.")
    review_action: str = Field(description="Concrete review action for this pitfall.")


class ContractBackgroundAgentOutput(BaseModel):
    summary: str
    background_card: BackgroundCard
    contract_category: ContractCategory
    related_documents: list[RelatedDocument]
    missing_questions: list[str]
    pitfalls: list[ReviewPitfall]


class ContractBackgroundResponse(ContractBackgroundAgentOutput):
    module: Literal["contract_background"]
    disclaimer: str
