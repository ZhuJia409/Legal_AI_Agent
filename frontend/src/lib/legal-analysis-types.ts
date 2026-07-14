export type LegalAnalysisModule =
  | "case_analysis"
  | "contract_background"
  | "contract_review_report";

export type RiskLevel = "unknown" | "low" | "medium" | "high";

export type AnalysisStatus = "complete" | "partial";
export type StageStatus = "succeeded" | "needs_input" | "failed" | "skipped";

// 顺序元组是九阶段契约的唯一来源，类型与展示层均从这里派生，避免各处漂移。
export const CASE_STAGE_ORDER = [
  "intake_screening",
  "fact_reconstruction",
  "evidence_review",
  "legal_classification",
  "deep_analysis",
  "risk_assessment",
  "strategy_options",
  "document_draft",
  "deadline_management",
] as const;

export type CaseStageCode = (typeof CASE_STAGE_ORDER)[number];
export type RiskDimension = "internal" | "opponent" | "execution_cost";
export type StrategyMode = "aggressive" | "balanced" | "conservative";

export type LegalAnalysisRequest = {
  title?: string | null;
  content?: string | null;
  file?: File;
  relatedFiles?: File[];
  reviewPerspective?: ReviewPerspective;
};

export type CaseStageError = {
  code: string;
  message: string;
};

export type CaseSourceRef = {
  paragraph_id: string;
  quote: string;
};

export type CaseFinding = {
  title: string;
  detail: string;
  source_refs: CaseSourceRef[];
};

export type CaseParty = {
  name: string;
  role: string;
  source_refs: CaseSourceRef[];
};

export type CaseClaim = {
  claimant: string;
  request: string;
  source_refs: CaseSourceRef[];
};

export type CaseTimelineEvent = {
  date: string;
  event: string;
  parties: string[];
  source_refs: CaseSourceRef[];
};

export type CaseDeadline = {
  name: string;
  trigger_date: string | null;
  deadline: string | null;
  uncertainty: string;
  source_refs: CaseSourceRef[];
};

export type CaseLegalRelation = {
  name: string;
  description: string;
  source_refs: CaseSourceRef[];
};

export type CaseCandidateCause = {
  name: string;
  reason: string;
  source_refs: CaseSourceRef[];
};

export type CaseIssueAnalysis = {
  issue_id: string;
  title: string;
  analysis: string;
  positions: string[];
  uncertainties: string[];
  missing_information: string[];
  source_refs: CaseSourceRef[];
};

export type CaseRiskItem = {
  dimension: RiskDimension;
  title: string;
  detail: string;
  risk_level: RiskLevel;
  mitigation: string;
  source_refs: CaseSourceRef[];
};

export type CaseStrategy = {
  mode: StrategyMode;
  summary: string;
  objective: string;
  steps: string[];
  prerequisites: string[];
  risks: string[];
  missing_information: string[];
};

export type CaseStageBase<TStage extends CaseStageCode> = {
  stage: TStage;
  status: StageStatus;
  summary: string;
  missing_information: string[];
  requires_human_review: boolean;
  error: CaseStageError | null;
};

export type IntakeStageResult = CaseStageBase<"intake_screening"> & {
  parties: CaseParty[];
  claims: CaseClaim[];
  case_route: string | null;
  red_flags: CaseFinding[];
};

export type FactStageResult = CaseStageBase<"fact_reconstruction"> & {
  timeline: CaseTimelineEvent[];
  key_facts: CaseFinding[];
  conflicts: CaseFinding[];
};

export type EvidenceStageResult = CaseStageBase<"evidence_review"> & {
  evidence_clues: CaseFinding[];
  gaps: CaseFinding[];
  reinforcement_plan: string[];
};

export type LegalStageResult = CaseStageBase<"legal_classification"> & {
  legal_relations: CaseLegalRelation[];
  candidate_causes: CaseCandidateCause[];
  procedure_questions: string[];
};

export type DeepAnalysisStageResult = CaseStageBase<"deep_analysis"> & {
  issues: CaseIssueAnalysis[];
};

export type RiskStageResult = CaseStageBase<"risk_assessment"> & {
  overall_risk_level: RiskLevel;
  risks: CaseRiskItem[];
};

export type StrategyStageResult = CaseStageBase<"strategy_options"> & {
  strategies: CaseStrategy[];
};

export type DocumentDraftStageResult = CaseStageBase<"document_draft"> & {
  draft_title: string;
  draft_sections: string[];
  quality_checks: string[];
};

export type DeadlineStageResult = CaseStageBase<"deadline_management"> & {
  deadlines: CaseDeadline[];
};

// 固定元组同时保证阶段数量、顺序和每一位置的专属结构。
export type CaseAnalysisStages = [
  IntakeStageResult,
  FactStageResult,
  EvidenceStageResult,
  LegalStageResult,
  DeepAnalysisStageResult,
  RiskStageResult,
  StrategyStageResult,
  DocumentDraftStageResult,
  DeadlineStageResult,
];

export type CaseStageResult = CaseAnalysisStages[number];

export type CaseAnalysisReport = {
  executive_summary: string;
  overall_risk_level: RiskLevel;
  key_findings: string[];
  recommended_actions: string[];
  limitations: string[];
  failed_stages: CaseStageCode[];
};

export type CaseAnalysisResponse = {
  module: "case_analysis";
  analysis_id: string;
  status: AnalysisStatus;
  summary: string;
  risk_level: RiskLevel;
  findings: string[];
  suggestions: string[];
  stages: CaseAnalysisStages;
  report: CaseAnalysisReport;
  draft_document?: CaseDraftDocumentInfo | null;
  disclaimer: string;
};

export type CaseDraftDocumentInfo = {
  format: "docx";
  filename: string;
  content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  size_bytes: number;
  sha256: string;
  generated_at: string;
  download_path: string;
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

export type AnalysisHistoryItem = {
  task_id?: string;
  analysis_id?: string;
  title: string | null;
  status: "complete" | "partial";
  risk_level: RiskLevel | ReviewRiskLevel;
  created_at: string;
};

export type AnalysisHistoryResponse = { items: AnalysisHistoryItem[] };

export type ApiErrorResponse = {
  error?: {
    code?: string;
    message?: string;
  };
};
