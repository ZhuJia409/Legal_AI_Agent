import { CASE_STAGE_ORDER } from "./legal-analysis-types";
import type {
  CaseAnalysisReport,
  CaseAnalysisResponse,
  CaseAnalysisStages,
  CaseStageCode,
  CaseStageResult,
  DeadlineStageResult,
  DeepAnalysisStageResult,
  DocumentDraftStageResult,
  EvidenceStageResult,
  FactStageResult,
  IntakeStageResult,
  LegalStageResult,
  RiskLevel,
  RiskStageResult,
  StageStatus,
  StrategyStageResult,
} from "./legal-analysis-types";

type Assert<T extends true> = T;
type IsExact<T, U> = [T] extends [U] ? ([U] extends [T] ? true : false) : false;

type ExpectedStageCode =
  | "intake_screening"
  | "fact_reconstruction"
  | "evidence_review"
  | "legal_classification"
  | "deep_analysis"
  | "risk_assessment"
  | "strategy_options"
  | "document_draft"
  | "deadline_management";
type ExpectedRiskLevel = "unknown" | "low" | "medium" | "high";
type ExpectedStageStatus = "succeeded" | "needs_input" | "failed" | "skipped";
type ExpectedSourceRef = { paragraph_id: string; quote: string };
type ExpectedFinding = {
  title: string;
  detail: string;
  source_refs: ExpectedSourceRef[];
};
type ExpectedStageBase<TStage extends ExpectedStageCode> = {
  stage: TStage;
  status: ExpectedStageStatus;
  summary: string;
  missing_information: string[];
  requires_human_review: boolean;
  error: { code: string; message: string } | null;
};
type ExpectedIntakeFields = {
  parties: Array<{ name: string; role: string; source_refs: ExpectedSourceRef[] }>;
  claims: Array<{ claimant: string; request: string; source_refs: ExpectedSourceRef[] }>;
  case_route: string | null;
  red_flags: ExpectedFinding[];
};
type ExpectedFactFields = {
  timeline: Array<{
    date: string;
    event: string;
    parties: string[];
    source_refs: ExpectedSourceRef[];
  }>;
  key_facts: ExpectedFinding[];
  conflicts: ExpectedFinding[];
};
type ExpectedEvidenceFields = {
  evidence_clues: ExpectedFinding[];
  gaps: ExpectedFinding[];
  reinforcement_plan: string[];
};
type ExpectedLegalFields = {
  legal_relations: Array<{
    name: string;
    description: string;
    source_refs: ExpectedSourceRef[];
  }>;
  candidate_causes: Array<{
    name: string;
    reason: string;
    source_refs: ExpectedSourceRef[];
  }>;
  procedure_questions: string[];
};
type ExpectedDeepAnalysisFields = {
  issues: Array<{
    issue_id: string;
    title: string;
    analysis: string;
    positions: string[];
    uncertainties: string[];
    missing_information: string[];
    source_refs: ExpectedSourceRef[];
  }>;
};
type ExpectedRiskFields = {
  overall_risk_level: ExpectedRiskLevel;
  risks: Array<{
    dimension: "internal" | "opponent" | "execution_cost";
    title: string;
    detail: string;
    risk_level: ExpectedRiskLevel;
    mitigation: string;
    source_refs: ExpectedSourceRef[];
  }>;
};
type ExpectedStrategyFields = {
  strategies: Array<{
    mode: "aggressive" | "balanced" | "conservative";
    summary: string;
    objective: string;
    steps: string[];
    prerequisites: string[];
    risks: string[];
    missing_information: string[];
  }>;
};
type ExpectedDocumentDraftFields = {
  draft_title: string;
  draft_sections: string[];
  quality_checks: string[];
  document_form?: {
    report_title: string;
    case_summary: string;
    strategies: Array<{
      mode: "aggressive" | "balanced" | "conservative";
      objective: string;
      actions: string[];
      prerequisites: string[];
      risks: string[];
    }>;
    draft_title: string;
    draft_purpose: string;
    key_facts: Array<{ text: string; source_refs: ExpectedSourceRef[] }>;
    core_positions_or_requests: string[];
    recommended_actions: string[];
    missing_information: string[];
    lawyer_review_items: string[];
  } | null;
};
type ExpectedDeadlineFields = {
  deadlines: Array<{
    name: string;
    trigger_date: string | null;
    deadline: string | null;
    uncertainty: string;
    source_refs: ExpectedSourceRef[];
  }>;
};

type ExpectedIntakeStage = ExpectedStageBase<"intake_screening"> & ExpectedIntakeFields;
type ExpectedFactStage = ExpectedStageBase<"fact_reconstruction"> & ExpectedFactFields;
type ExpectedEvidenceStage = ExpectedStageBase<"evidence_review"> & ExpectedEvidenceFields;
type ExpectedLegalStage = ExpectedStageBase<"legal_classification"> & ExpectedLegalFields;
type ExpectedDeepAnalysisStage = ExpectedStageBase<"deep_analysis"> &
  ExpectedDeepAnalysisFields;
type ExpectedRiskStage = ExpectedStageBase<"risk_assessment"> & ExpectedRiskFields;
type ExpectedStrategyStage = ExpectedStageBase<"strategy_options"> & ExpectedStrategyFields;
type ExpectedDocumentDraftStage = ExpectedStageBase<"document_draft"> &
  ExpectedDocumentDraftFields;
type ExpectedDeadlineStage = ExpectedStageBase<"deadline_management"> &
  ExpectedDeadlineFields;

type ExpectedCaseStageResult =
  | ExpectedIntakeStage
  | ExpectedFactStage
  | ExpectedEvidenceStage
  | ExpectedLegalStage
  | ExpectedDeepAnalysisStage
  | ExpectedRiskStage
  | ExpectedStrategyStage
  | ExpectedDocumentDraftStage
  | ExpectedDeadlineStage;
type ExpectedCaseAnalysisStages = [
  ExpectedIntakeStage,
  ExpectedFactStage,
  ExpectedEvidenceStage,
  ExpectedLegalStage,
  ExpectedDeepAnalysisStage,
  ExpectedRiskStage,
  ExpectedStrategyStage,
  ExpectedDocumentDraftStage,
  ExpectedDeadlineStage,
];
type ExpectedCaseAnalysisReport = {
  executive_summary: string;
  overall_risk_level: ExpectedRiskLevel;
  key_findings: string[];
  recommended_actions: string[];
  limitations: string[];
  failed_stages: ExpectedStageCode[];
};
type ExpectedCaseAnalysisResponse = {
  module: "case_analysis";
  analysis_id: string;
  status: "complete" | "partial";
  summary: string;
  risk_level: ExpectedRiskLevel;
  findings: string[];
  suggestions: string[];
  stages: ExpectedCaseAnalysisStages;
  report: ExpectedCaseAnalysisReport;
  disclaimer: string;
};
type StageSpecificFields<TStage> = Omit<TStage, keyof ExpectedStageBase<ExpectedStageCode>>;

type _StageOrder = Assert<
  IsExact<
    typeof CASE_STAGE_ORDER,
    readonly [
      "intake_screening",
      "fact_reconstruction",
      "evidence_review",
      "legal_classification",
      "deep_analysis",
      "risk_assessment",
      "strategy_options",
      "document_draft",
      "deadline_management",
    ]
  >
>;
type _StageCode = Assert<IsExact<CaseStageCode, ExpectedStageCode>>;
type _RiskLevel = Assert<IsExact<RiskLevel, ExpectedRiskLevel>>;
type _StageStatus = Assert<IsExact<StageStatus, ExpectedStageStatus>>;
type _StageUnion = Assert<IsExact<CaseStageResult, ExpectedCaseStageResult>>;
type _StagesTuple = Assert<IsExact<CaseAnalysisStages, ExpectedCaseAnalysisStages>>;
type _ResponseUsesTuple = Assert<
  IsExact<CaseAnalysisResponse["stages"], CaseAnalysisStages>
>;
type _Report = Assert<IsExact<CaseAnalysisReport, ExpectedCaseAnalysisReport>>;
type _Response = Assert<IsExact<CaseAnalysisResponse, ExpectedCaseAnalysisResponse>>;

// 每阶段比较独有字段，避免“从同一联合类型提取后再与自身比较”的恒真断言。
type _IntakeFields = Assert<
  IsExact<StageSpecificFields<IntakeStageResult>, ExpectedIntakeFields>
>;
type _FactFields = Assert<IsExact<StageSpecificFields<FactStageResult>, ExpectedFactFields>>;
type _EvidenceFields = Assert<
  IsExact<StageSpecificFields<EvidenceStageResult>, ExpectedEvidenceFields>
>;
type _LegalFields = Assert<IsExact<StageSpecificFields<LegalStageResult>, ExpectedLegalFields>>;
type _DeepAnalysisFields = Assert<
  IsExact<StageSpecificFields<DeepAnalysisStageResult>, ExpectedDeepAnalysisFields>
>;
type _RiskFields = Assert<IsExact<StageSpecificFields<RiskStageResult>, ExpectedRiskFields>>;
type _StrategyFields = Assert<
  IsExact<StageSpecificFields<StrategyStageResult>, ExpectedStrategyFields>
>;
type _DocumentDraftFields = Assert<
  IsExact<StageSpecificFields<DocumentDraftStageResult>, ExpectedDocumentDraftFields>
>;
type _DeadlineFields = Assert<
  IsExact<StageSpecificFields<DeadlineStageResult>, ExpectedDeadlineFields>
>;
