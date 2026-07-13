export type LegalAnalysisModule = "case_analysis" | "contract_background";

export type RiskLevel = "low" | "medium" | "high";

export type LegalAnalysisRequest = {
  title?: string | null;
  content?: string | null;
  file?: File;
  relatedFiles?: File[];
};

export type CaseAnalysisResponse = {
  module: "case_analysis";
  summary: string;
  risk_level: RiskLevel;
  findings: string[];
  suggestions: string[];
  disclaimer: string;
};

export type ContractCategory =
  | "commercial_transaction"
  | "service_entrustment"
  | "construction_project"
  | "technology_data_ip"
  | "finance_guarantee"
  | "investment_ma"
  | "labor_hr"
  | "framework_cooperation"
  | "other_unknown";

export type RelatedDocumentStatus = "provided" | "missing";

export type SourceRef = {
  paragraph_id: string;
  clause_path?: string | null;
  quote: string;
};

export type EvidenceText = {
  text?: string | null;
  source_refs: SourceRef[];
};

export type BackgroundCard = {
  commercial_purpose: EvidenceText;
  party_position: EvidenceText;
  counterparty_identity: EvidenceText;
  amount_term_scope: EvidenceText;
  business_focus: EvidenceText;
  urgency_deadline: EvidenceText;
};

export type RelatedDocument = {
  name: string;
  status: RelatedDocumentStatus;
};

export type ReviewPitfall = {
  name: string;
  risk: string;
  review_action: string;
  source_refs: SourceRef[];
};

export type ContractBackgroundResponse = {
  module: "contract_background";
  summary: string;
  background_card: BackgroundCard;
  contract_category: ContractCategory;
  related_documents: RelatedDocument[];
  missing_questions: string[];
  pitfalls: ReviewPitfall[];
  disclaimer: string;
};

export type LegalAnalysisResponse = CaseAnalysisResponse | ContractBackgroundResponse;

export type ApiErrorResponse = {
  error?: {
    code?: string;
    message?: string;
  };
};
