export type LegalAnalysisModule =
  | "case_analysis"
  | "contract_background"
  | "contract_review_report";

export type RiskLevel = "low" | "medium" | "high";

export type LegalAnalysisRequest = {
  title?: string | null;
  content?: string | null;
  file?: File;
  relatedFiles?: File[];
  reviewPerspective?: ReviewPerspective;
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
  document_name?: string | null;
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

export type ReviewPerspective = "neutral" | "party_a" | "party_b";
export type ReviewRiskLevel = "fatal" | "high" | "medium" | "low";
export type ReviewModule =
  | "party_qualification"
  | "form_structure"
  | "general_substantive"
  | "related_document_comparison"
  | "contract_type_special";
export type ReviewModuleStatus = "succeeded" | "failed" | "skipped";
export type SigningRecommendation = "do_not_sign" | "conditional" | "can_sign_after_review";

export type ContractTypeCode =
  | "sale"
  | "utility_supply"
  | "gift"
  | "loan"
  | "lease"
  | "finance_lease"
  | "work_contract"
  | "construction"
  | "transport"
  | "technology"
  | "custody"
  | "warehousing"
  | "entrustment"
  | "property_service"
  | "commission_agency"
  | "intermediary"
  | "partnership"
  | "guarantee"
  | "factoring"
  | "employment"
  | "nda"
  | "saas_software_service"
  | "equity_transfer"
  | "procurement_framework"
  | "franchise"
  | "investment_capital_increase"
  | "asset_business_acquisition"
  | "credit_assignment_debt_assumption"
  | "mortgage_pledge"
  | "ip_license"
  | "insurance"
  | "joint_venture"
  | "dpa"
  | "asset_custody";

export type ContractTypeSelection = {
  code: ContractTypeCode;
  label: string;
  rule_pack: string;
  is_primary: boolean;
  reason: string;
  source_refs: SourceRef[];
};

export type ReviewFinding = {
  finding_id: string;
  module: ReviewModule;
  risk_level: ReviewRiskLevel;
  contract_location: string;
  issue: string;
  basis: string;
  impact: string;
  suggestion: string;
  negotiation_strategy: string;
  source_refs: SourceRef[];
  source_finding_ids: string[];
  requires_human_review: boolean;
};

export type ReviewModuleResult = {
  module: ReviewModule;
  status: ReviewModuleStatus;
  summary: string;
  findings: ReviewFinding[];
  missing_evidence: string[];
  error?: { code: string; message: string } | null;
};

export type ContractReviewReport = {
  executive_summary: string;
  overall_risk_level: ReviewRiskLevel;
  signing_recommendation: SigningRecommendation;
  preconditions: string[];
  findings: ReviewFinding[];
  limitations: string[];
  failed_modules: ReviewModule[];
};

export type ReportDocumentInfo = {
  format: "pdf";
  filename: string;
  content_type: "application/pdf";
  size_bytes: number;
  sha256: string;
  generated_at: string;
  download_path: string;
};

export type ContractReviewReportResponse = {
  module: "contract_review_report";
  task_id: string;
  status: "complete" | "partial";
  review_perspective: ReviewPerspective;
  background: ContractBackgroundResponse;
  contract_types: ContractTypeSelection[];
  modules: ReviewModuleResult[];
  report: ContractReviewReport;
  disclaimer: string;
  report_document?: ReportDocumentInfo | null;
};

export type LegalAnalysisResponse =
  | CaseAnalysisResponse
  | ContractBackgroundResponse
  | ContractReviewReportResponse;

export type ApiErrorResponse = {
  error?: {
    code?: string;
    message?: string;
  };
};
