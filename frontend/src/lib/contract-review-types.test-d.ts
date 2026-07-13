import type {
  ContractReviewReportResponse,
  ReportDocumentInfo,
  ReviewModuleResult,
} from "./legal-analysis-types";

type Assert<T extends true> = T;
type IsExact<T, U> = [T] extends [U] ? ([U] extends [T] ? true : false) : false;

declare const response: ContractReviewReportResponse;
declare const moduleResult: ReviewModuleResult;
declare const reportDocument: ReportDocumentInfo;

type _ModuleLiteral = Assert<IsExact<typeof response.module, "contract_review_report">>;
type _ModuleStatus = Assert<
  IsExact<typeof moduleResult.status, "succeeded" | "failed" | "skipped">
>;
type _Perspective = Assert<
  IsExact<typeof response.review_perspective, "neutral" | "party_a" | "party_b">
>;
type _ReportFormat = Assert<IsExact<typeof reportDocument.format, "pdf">>;
type _OptionalReportDocument = Assert<
  IsExact<typeof response.report_document, ReportDocumentInfo | null | undefined>
>;
