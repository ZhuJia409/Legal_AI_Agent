import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  FileWarning,
  Info,
  ListChecks,
  ShieldAlert,
  Tags,
} from "lucide-react";

import type {
  ContractBackgroundResponse,
  ContractReviewReportResponse,
  ReviewModule,
  ReviewModuleStatus,
  ReviewRiskLevel,
  SigningRecommendation,
  SourceRef,
} from "@/lib/legal-analysis-types";
import { cn } from "@/lib/utils";

import { ContractReviewDocumentCard } from "./contract-review-document-card";

const RISK_LABELS: Record<ReviewRiskLevel, string> = {
  fatal: "致命风险",
  high: "高风险",
  medium: "中风险",
  low: "低风险",
};

const RISK_STYLES: Record<ReviewRiskLevel, string> = {
  fatal: "border-red-300 bg-red-100 text-red-950",
  high: "border-rose-200 bg-rose-50 text-rose-800",
  medium: "border-amber-200 bg-amber-50 text-amber-800",
  low: "border-emerald-200 bg-emerald-50 text-emerald-800",
};

const MODULE_LABELS: Record<ReviewModule, string> = {
  party_qualification: "主体资格",
  form_structure: "形式与结构",
  general_substantive: "通用实质审查",
  related_document_comparison: "关联文件比对",
  contract_type_special: "合同类型专项",
};

const STATUS_LABELS: Record<ReviewModuleStatus, string> = {
  succeeded: "已完成",
  failed: "失败",
  skipped: "已跳过",
};

const SIGNING_LABELS: Record<SigningRecommendation, string> = {
  do_not_sign: "暂不建议签署",
  conditional: "满足前提后再签署",
  can_sign_after_review: "专业复核后可考虑签署",
};

type BackgroundFieldKey = keyof ContractBackgroundResponse["background_card"];

const CATEGORY_LABELS: Record<ContractBackgroundResponse["contract_category"], string> = {
  commercial_transaction: "商事交易",
  service_entrustment: "服务委托",
  construction_project: "建设工程",
  technology_data_ip: "技术/数据/IP",
  finance_guarantee: "金融担保",
  investment_ma: "投资并购",
  labor_hr: "劳动人事",
  framework_cooperation: "框架合作",
  other_unknown: "其他/待确认",
};

const BACKGROUND_FIELDS: Array<{ key: BackgroundFieldKey; label: string }> = [
  { key: "commercial_purpose", label: "商业目的" },
  { key: "party_position", label: "合同立场" },
  { key: "counterparty_identity", label: "双方身份与关系" },
  { key: "amount_term_scope", label: "金额/期限/标的规模" },
  { key: "business_focus", label: "业务方特殊关注点" },
  { key: "urgency_deadline", label: "紧急程度/截止时间" },
];

export function ContractReviewReportResult({
  result,
}: {
  result: ContractReviewReportResponse;
}) {
  return (
    <div className="mt-6 space-y-5">
      {result.status === "partial" ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-rose-900">
          <div className="flex gap-3">
            <AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0" />
            <div>
              <p className="text-sm font-semibold">审查报告不完整</p>
              <p className="mt-1 text-xs leading-5">存在未完成模块，本报告不可作为签署依据。</p>
            </div>
          </div>
        </div>
      ) : null}

      {result.report_document ? (
        <ContractReviewDocumentCard
          document={result.report_document}
          isPartial={result.status === "partial"}
        />
      ) : null}

      <BackgroundSnapshot background={result.background} />

      <div className="flex flex-wrap gap-2">
        <span
          className={cn(
            "rounded-md border px-3 py-1.5 text-sm font-semibold",
            RISK_STYLES[result.report.overall_risk_level],
          )}
        >
          {RISK_LABELS[result.report.overall_risk_level]}
        </span>
        <span className="rounded-md border border-zinc-200 bg-zinc-50 px-3 py-1.5 text-sm font-semibold text-zinc-700">
          {SIGNING_LABELS[result.report.signing_recommendation]}
        </span>
      </div>

      <section>
        <h3 className="text-sm font-semibold text-zinc-900">综合审查结论</h3>
        <p className="mt-2 text-sm leading-6 text-zinc-600">{result.report.executive_summary}</p>
      </section>

      {result.contract_types.length ? (
        <section>
          <h3 className="text-sm font-semibold text-zinc-900">确认的合同类型</h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {result.contract_types.map((item) => (
              <span
                className={cn(
                  "rounded-md border px-2.5 py-1 text-xs font-semibold",
                  item.is_primary
                    ? "border-[#214a4b] bg-[#edf4ef] text-[#214a4b]"
                    : "border-zinc-200 bg-white text-zinc-600",
                )}
                key={item.code}
                title={item.reason}
              >
                {item.label}{item.is_primary ? " · 主类型" : ""}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      <section>
        <h3 className="text-sm font-semibold text-zinc-900">模块完成情况</h3>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {result.modules.map((item) => (
            <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-3" key={item.module}>
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-zinc-800">{MODULE_LABELS[item.module]}</p>
                <ModuleStatusIcon status={item.status} />
              </div>
              <p className="mt-1 text-xs font-medium text-zinc-500">{STATUS_LABELS[item.status]}</p>
              <p className="mt-2 text-xs leading-5 text-zinc-600">{item.summary}</p>
              {item.missing_evidence.length ? (
                <div className="mt-3 border-t border-zinc-200 pt-2">
                  <p className="text-[11px] font-semibold text-amber-800">缺失证据</p>
                  <ul className="mt-1 space-y-1 text-xs leading-5 text-amber-800">
                    {item.missing_evidence.map((evidence, index) => (
                      <li key={`${item.module}-missing-${index}`}>· {evidence}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {item.error ? (
                <p className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-2.5 py-2 text-xs leading-5 text-rose-800">
                  {item.error.message}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      </section>

      <section>
        <div className="flex items-center gap-2">
          <ShieldAlert aria-hidden="true" className="h-4 w-4 text-[#214a4b]" />
          <h3 className="text-sm font-semibold text-zinc-900">分级风险清单</h3>
        </div>
        {result.report.findings.length ? (
          <div className="mt-3 space-y-3">
            {result.report.findings.map((finding) => (
              <article className="rounded-lg border border-zinc-200 bg-white p-4" key={finding.finding_id}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-zinc-900">{finding.issue}</p>
                  <span
                    className={cn(
                      "rounded-md border px-2 py-1 text-xs font-semibold",
                      RISK_STYLES[finding.risk_level],
                    )}
                  >
                    {RISK_LABELS[finding.risk_level]}
                  </span>
                </div>
                <p className="mt-2 text-xs text-zinc-500">
                  {MODULE_LABELS[finding.module]} · {finding.contract_location || "位置待确认"}
                </p>
                <ReportLine label="审查依据" value={finding.basis} />
                <ReportLine label="可能影响" value={finding.impact} />
                <ReportLine label="修改建议" value={finding.suggestion} />
                <ReportLine label="谈判策略" value={finding.negotiation_strategy} />
                <EvidenceRefs refs={finding.source_refs} />
              </article>
            ))}
          </div>
        ) : (
          <p className="mt-2 text-sm leading-6 text-zinc-500">未生成可验证的风险项。</p>
        )}
      </section>

      <SimpleList title="签署前提" items={result.report.preconditions} />
      <SimpleList title="证据与范围限制" items={result.report.limitations} warning />

      <div className="rounded-lg border border-zinc-200 bg-[#f7f8f6] p-4">
        <div className="flex gap-2">
          <Info aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-[#214a4b]" />
          <p className="text-xs leading-5 text-zinc-500">{result.disclaimer}</p>
        </div>
      </div>
    </div>
  );
}

function BackgroundSnapshot({
  background,
}: {
  background: ContractBackgroundResponse;
}) {
  return (
    <section className="rounded-lg border border-zinc-200 bg-[#f7f8f6] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold tracking-wide text-zinc-500">Phase 0 · 合同背景</p>
          <p className="mt-1 text-sm leading-6 text-zinc-700">{background.summary}</p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-md border border-[#b9d8cc] bg-[#eef8f2] px-2.5 py-1 text-xs font-semibold text-[#214a4b]">
          <Tags aria-hidden="true" className="h-3.5 w-3.5" />
          {CATEGORY_LABELS[background.contract_category]}
        </span>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        {BACKGROUND_FIELDS.map((field) => {
          const value = background.background_card[field.key];
          return (
            <div className="rounded-md border border-zinc-200 bg-white p-3" key={field.key}>
              <p className="text-xs font-semibold text-zinc-500">{field.label}</p>
              <p className="mt-1 text-sm leading-6 text-zinc-700">
                {value.text || "暂未从合同文本确认"}
              </p>
              <EvidenceRefs refs={value.source_refs} />
            </div>
          );
        })}
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div>
          <p className="text-xs font-semibold text-zinc-600">关联文件提示</p>
          {background.related_documents.length ? (
            <ul className="mt-2 space-y-2">
              {background.related_documents.map((document, index) => (
                <li
                  className="flex items-center justify-between gap-3 rounded-md border border-zinc-200 bg-white px-3 py-2 text-xs"
                  key={`${document.name}-${index}`}
                >
                  <span className="min-w-0 break-words text-zinc-700">{document.name}</span>
                  <span
                    className={cn(
                      "shrink-0 rounded border px-2 py-0.5 font-semibold",
                      document.status === "provided"
                        ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                        : "border-rose-200 bg-rose-50 text-rose-700",
                    )}
                  >
                    {document.status === "provided" ? "已提供" : "缺失"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-xs leading-5 text-zinc-500">暂无关联文件提示。</p>
          )}
        </div>

        <div>
          <div className="flex items-center gap-1.5">
            <ListChecks aria-hidden="true" className="h-3.5 w-3.5 text-[#214a4b]" />
            <p className="text-xs font-semibold text-zinc-600">初步陷阱</p>
          </div>
          {background.pitfalls.length ? (
            <ul className="mt-2 space-y-2">
              {background.pitfalls.map((pitfall, index) => (
                <li
                  className="rounded-md border border-zinc-200 bg-white px-3 py-2 text-xs leading-5 text-zinc-600"
                  key={`${pitfall.name}-${index}`}
                >
                  <p className="font-semibold text-zinc-800">{pitfall.name}</p>
                  <p className="mt-1">{pitfall.risk}</p>
                  <p className="mt-1 text-zinc-700">{pitfall.review_action}</p>
                  <EvidenceRefs refs={pitfall.source_refs} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-xs leading-5 text-zinc-500">暂无特别陷阱提示。</p>
          )}
        </div>
      </div>

      {background.missing_questions.length ? (
        <div className="mt-4">
          <SimpleList title="背景待确认问题" items={background.missing_questions} warning />
        </div>
      ) : null}
    </section>
  );
}

function ModuleStatusIcon({ status }: { status: ReviewModuleStatus }) {
  if (status === "succeeded") {
    return <CheckCircle2 aria-label="已完成" className="h-4 w-4 text-emerald-600" />;
  }
  if (status === "failed") {
    return <FileWarning aria-label="失败" className="h-4 w-4 text-rose-600" />;
  }
  return <CircleDashed aria-label="已跳过" className="h-4 w-4 text-zinc-400" />;
}

function ReportLine({ label, value }: { label: string; value: string }) {
  return (
    <p className="mt-2 text-sm leading-6 text-zinc-600">
      <span className="font-medium text-zinc-800">{label}：</span>
      {value}
    </p>
  );
}

function EvidenceRefs({ refs }: { refs: SourceRef[] }) {
  if (!refs.length) return null;
  return (
    <div className="mt-3 space-y-2">
      {refs.map((ref) => (
        <details
          className="rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2"
          key={`${ref.document_name ?? "main"}-${ref.paragraph_id}`}
        >
          <summary className="cursor-pointer text-xs font-medium leading-5 text-zinc-600">
            {ref.document_name ?? "主合同"} · {ref.clause_path ?? ref.paragraph_id}
          </summary>
          <p className="mt-2 whitespace-pre-wrap break-words border-t border-zinc-200 pt-2 text-xs leading-5 text-zinc-500">
            {ref.quote}
          </p>
        </details>
      ))}
    </div>
  );
}

function SimpleList({ items, title, warning = false }: { items: string[]; title: string; warning?: boolean }) {
  if (!items.length) return null;
  return (
    <section>
      <h3 className="text-sm font-semibold text-zinc-900">{title}</h3>
      <ul className="mt-3 space-y-2">
        {items.map((item, index) => (
          <li
            className={cn(
              "rounded-md border px-3 py-2 text-sm leading-6",
              warning
                ? "border-amber-200 bg-amber-50 text-amber-900"
                : "border-zinc-200 bg-zinc-50 text-zinc-600",
            )}
            key={`${title}-${index}`}
          >
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}
