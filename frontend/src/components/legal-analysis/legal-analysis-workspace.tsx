"use client";

import {
  AlertTriangle,
  BriefcaseBusiness,
  ClipboardCheck,
  FileText,
  Info,
  ListChecks,
  Loader2,
  Scale,
  Send,
  Tags,
  Upload,
} from "lucide-react";
import { FormEvent, useRef, useState } from "react";

import {
  LegalAnalysisEndpoint,
  submitLegalAnalysis,
} from "@/lib/legal-analysis-api";
import type {
  CaseAnalysisResponse,
  ContractBackgroundResponse,
  ContractCategory,
  ContractReviewReportResponse,
  LegalAnalysisResponse,
  RelatedDocumentStatus,
  RiskLevel,
  ReviewPerspective,
  SourceRef,
} from "@/lib/legal-analysis-types";
import { cn } from "@/lib/utils";
import { ContractReviewReportResult } from "./contract-review-report-result";

type ModuleId = "case" | "contract";

type FormState = {
  title: string;
  file?: File;
  relatedFiles: File[];
  reviewPerspective: ReviewPerspective;
};

type ModuleConfig = {
  id: ModuleId;
  label: string;
  endpoint: LegalAnalysisEndpoint;
  icon: typeof Scale;
  titlePlaceholder: string;
  submitLabel: string;
};

type BackgroundFieldKey = keyof ContractBackgroundResponse["background_card"];

const MODULES: ModuleConfig[] = [
  {
    id: "case",
    label: "案件分析",
    endpoint: "case-analyses",
    icon: Scale,
    titlePlaceholder: "例如：买卖合同纠纷",
    submitLabel: "案件分析",
  },
  {
    id: "contract",
    label: "合同审查",
    endpoint: "contract-review-reports",
    icon: ClipboardCheck,
    titlePlaceholder: "例如：技术服务合同",
    submitLabel: "开始完整合同审查",
  },
];

const EMPTY_FORM: FormState = {
  title: "",
  relatedFiles: [],
  reviewPerspective: "neutral",
};

const RISK_LABELS: Record<RiskLevel, string> = {
  low: "低风险",
  medium: "中风险",
  high: "高风险",
};

const RISK_STYLES: Record<RiskLevel, string> = {
  low: "border-emerald-200 bg-emerald-50 text-emerald-800",
  medium: "border-amber-200 bg-amber-50 text-amber-800",
  high: "border-rose-200 bg-rose-50 text-rose-800",
};

const CATEGORY_LABELS: Record<ContractCategory, string> = {
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

const RELATED_STATUS_LABELS: Record<RelatedDocumentStatus, string> = {
  provided: "有",
  missing: "缺失",
};

const RELATED_STATUS_STYLES: Record<RelatedDocumentStatus, string> = {
  provided: "border-emerald-200 bg-emerald-50 text-emerald-800",
  missing: "border-rose-200 bg-rose-50 text-rose-800",
};

const RELATED_DOC_NAME_MAP: Record<string, string> = {
  "related-document checklist": "关联文件清单",
  "negotiation minutes/meeting records": "谈判纪要/会议记录",
  emails: "邮件往来",
  "chat records": "聊天记录",
  "framework agreement/master contract": "框架协议/主合同",
  "tender documents and award notice": "招标文件及中标通知书",
  "technical specification/SOW/requirements document": "技术规格/SOW/需求文档",
  "historical contracts": "历史合同",
  "due diligence report": "尽职调查报告",
  "project approval/internal approval documents": "项目立项/内部审批文件",
  "counterparty publicity materials/quotation": "相对方公示材料/报价单",
};

const PITFALL_NAME_MAP: Record<string, string> = {
  "name-substance mismatch": "名实不符",
  "LOI effectiveness": "意向书效力",
  "hidden pre-contractual liability triggers": "隐形缔约过失责任触发点",
};

const BACKGROUND_FIELDS: Array<{ key: BackgroundFieldKey; label: string }> = [
  { key: "commercial_purpose", label: "商业目的" },
  { key: "party_position", label: "合同立场" },
  { key: "counterparty_identity", label: "双方身份与关系" },
  { key: "amount_term_scope", label: "金额/期限/标的规模" },
  { key: "business_focus", label: "业务方特殊关注点" },
  { key: "urgency_deadline", label: "紧急程度/截止时间" },
];

const ALLOWED_MIME_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];

const ALLOWED_EXTENSIONS = [".pdf", ".docx"];

function isAllowedFile(file: File): boolean {
  if (ALLOWED_MIME_TYPES.includes(file.type)) return true;
  const name = file.name.toLowerCase();
  return ALLOWED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function isContractBackgroundResponse(
  result: LegalAnalysisResponse,
): result is ContractBackgroundResponse {
  return result.module === "contract_background";
}

function isContractReviewReportResponse(
  result: LegalAnalysisResponse,
): result is ContractReviewReportResponse {
  return result.module === "contract_review_report";
}

export function LegalAnalysisWorkspace() {
  const [activeModuleId, setActiveModuleId] = useState<ModuleId>("case");
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [result, setResult] = useState<LegalAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [contentError, setContentError] = useState<string | null>(null);
  const [relatedFilesError, setRelatedFilesError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const relatedFilesInputRef = useRef<HTMLInputElement>(null);

  const activeModule = MODULES.find((item) => item.id === activeModuleId) ?? MODULES[0];
  const ActiveIcon = activeModule.icon;

  function switchModule(moduleId: ModuleId) {
    setActiveModuleId(moduleId);
    setForm(EMPTY_FORM);
    setResult(null);
    setError(null);
    setContentError(null);
    setRelatedFilesError(null);
  }

  function handleFileSelect(selectedFile: File) {
    if (!isAllowedFile(selectedFile)) {
      setContentError("请上传 PDF 或 DOCX 格式的文件。");
      return;
    }

    setForm((current) => ({ ...current, file: selectedFile }));
    setContentError(null);
  }

  function clearFile() {
    setForm((current) => ({ ...current, file: undefined }));
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  function handleRelatedFilesSelect(selectedFiles: File[]) {
    const invalidFile = selectedFiles.find((file) => !isAllowedFile(file));
    if (invalidFile) {
      setRelatedFilesError(`关联文件“${invalidFile.name}”不是 PDF 或 DOCX 格式。`);
      return;
    }

    setForm((current) => {
      const existing = new Set(
        current.relatedFiles.map((file) => `${file.name}-${file.size}-${file.lastModified}`),
      );
      const additions = selectedFiles.filter(
        (file) => !existing.has(`${file.name}-${file.size}-${file.lastModified}`),
      );
      return { ...current, relatedFiles: [...current.relatedFiles, ...additions] };
    });
    setRelatedFilesError(null);
    if (relatedFilesInputRef.current) {
      relatedFilesInputRef.current.value = "";
    }
  }

  function removeRelatedFile(index: number) {
    setForm((current) => ({
      ...current,
      relatedFiles: current.relatedFiles.filter((_, fileIndex) => fileIndex !== index),
    }));
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    const droppedFile = event.dataTransfer.files?.[0];
    if (droppedFile) {
      handleFileSelect(droppedFile);
    }
  }

  function handleDragOver(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(true);
  }

  function handleDragLeave() {
    setIsDragging(false);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!form.file) {
      setContentError("请先上传需要分析的 PDF 或 DOCX 文件。");
      setResult(null);
      setError(null);
      return;
    }

    setIsSubmitting(true);
    setContentError(null);
    setError(null);

    try {
      const response = await submitLegalAnalysis(activeModule.endpoint, {
        title: form.title.trim() || null,
        file: form.file,
        relatedFiles: activeModule.id === "contract" ? form.relatedFiles : [],
        reviewPerspective:
          activeModule.id === "contract" ? form.reviewPerspective : undefined,
      });
      setResult(response);
    } catch (submitError) {
      const message =
        submitError instanceof Error ? submitError.message : "分析服务暂时不可用，请稍后重试。";
      setResult(null);
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#f7f8f6] text-zinc-900">
      <div className="mx-auto grid min-h-screen w-full max-w-7xl gap-4 px-4 py-4 lg:grid-cols-[260px_minmax(0,1fr)_420px] lg:px-6">
        <aside className="rounded-lg border border-zinc-200 bg-white p-6 shadow-sm lg:min-h-[calc(100vh-2rem)]">
          <div className="flex items-center gap-3 border-b border-zinc-200 pb-5">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#214a4b] text-white">
              <BriefcaseBusiness aria-hidden="true" className="h-5 w-5" />
            </div>
            <p className="text-sm font-semibold text-zinc-900">Legal AI Agent</p>
          </div>

          <nav aria-label="分析模块" className="mt-5 space-y-2">
            {MODULES.map((item) => {
              const Icon = item.icon;
              const active = item.id === activeModule.id;
              return (
                <button
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#214a4b] focus-visible:ring-offset-2",
                    active
                      ? "border-[#214a4b] bg-[#214a4b] text-white"
                      : "border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50",
                  )}
                  key={item.id}
                  onClick={() => switchModule(item.id)}
                  type="button"
                >
                  <Icon aria-hidden="true" className="h-5 w-5 shrink-0" />
                  <span className="text-sm font-semibold">{item.label}</span>
                </button>
              );
            })}
          </nav>
        </aside>

        <section className="rounded-lg border border-zinc-200 bg-white p-6 shadow-sm lg:min-h-[calc(100vh-2rem)]">
          <div className="flex items-center gap-3 border-b border-zinc-200 pb-5">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#edf4ef] text-[#214a4b]">
              <ActiveIcon aria-hidden="true" className="h-5 w-5" />
            </div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">
              {activeModule.label}
            </h1>
          </div>

          <form className="mt-6 space-y-6" onSubmit={handleSubmit}>
            <label className="block">
              <span className="text-sm font-medium text-zinc-800">标题</span>
              <input
                className="mt-2 h-11 w-full rounded-lg border border-zinc-300 bg-white px-3 text-sm text-zinc-900 outline-none transition-colors placeholder:text-zinc-400 focus:border-[#214a4b] focus-visible:ring-2 focus-visible:ring-[#214a4b]/30"
                maxLength={200}
                onChange={(event) =>
                  setForm((current) => ({ ...current, title: event.target.value }))
                }
                placeholder={activeModule.titlePlaceholder}
                value={form.title}
              />
            </label>

            <label className="block">
              <span className="text-sm font-medium text-zinc-800">正文内容</span>
              <div
                className={cn(
                  "mt-2 flex min-h-[360px] w-full cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed bg-white px-6 py-8 text-center transition-colors",
                  isDragging
                    ? "border-[#214a4b] bg-zinc-50"
                    : contentError
                      ? "border-rose-400"
                      : "border-zinc-300 hover:border-zinc-400",
                )}
                onClick={() => fileInputRef.current?.click()}
                onDragLeave={handleDragLeave}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
              >
                <input
                  accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  className="hidden"
                  onChange={(event) => {
                    const selectedFile = event.target.files?.[0];
                    if (selectedFile) {
                      handleFileSelect(selectedFile);
                    }
                  }}
                  ref={fileInputRef}
                  type="file"
                />
                {form.file ? (
                  <div className="flex w-full items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <FileText aria-hidden="true" className="h-6 w-6 shrink-0 text-[#214a4b]" />
                      <div className="min-w-0 text-left">
                        <p className="truncate text-sm font-medium text-zinc-900">
                          {form.file.name}
                        </p>
                        <p className="text-xs text-zinc-500">{formatFileSize(form.file.size)}</p>
                      </div>
                    </div>
                    <button
                      className="shrink-0 rounded-md px-2 py-1 text-xs text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
                      onClick={(event) => {
                        event.stopPropagation();
                        clearFile();
                      }}
                      type="button"
                    >
                      删除
                    </button>
                  </div>
                ) : (
                  <div>
                    <Upload aria-hidden="true" className="mx-auto h-8 w-8 text-zinc-400" />
                    <p className="mt-3 text-sm font-medium text-zinc-700">
                      点击或拖拽上传 PDF / DOCX 文件
                    </p>
                  </div>
                )}
              </div>
              {contentError ? (
                <span className="mt-2 flex items-center gap-2 text-sm text-rose-700">
                  <AlertTriangle aria-hidden="true" className="h-4 w-4" />
                  {contentError}
                </span>
              ) : null}
            </label>

            {activeModule.id === "contract" ? (
              <div className="space-y-6">
                <label className="block">
                  <span className="text-sm font-medium text-zinc-800">审查立场</span>
                  <select
                    className="mt-2 h-11 w-full rounded-lg border border-zinc-300 bg-white px-3 text-sm text-zinc-900 outline-none focus:border-[#214a4b] focus-visible:ring-2 focus-visible:ring-[#214a4b]/30"
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        reviewPerspective: event.target.value as ReviewPerspective,
                      }))
                    }
                    value={form.reviewPerspective}
                  >
                    <option value="neutral">中立审查</option>
                    <option value="party_a">按甲方利益审查</option>
                    <option value="party_b">按乙方利益审查</option>
                  </select>
                  <span className="mt-1 block text-xs leading-5 text-zinc-500">
                    修改建议和谈判策略将按所选立场生成；不确定时请选择中立。
                  </span>
                </label>

                <section aria-labelledby="related-files-label">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <h2 className="text-sm font-medium text-zinc-800" id="related-files-label">
                        关联文件（可选）
                      </h2>
                      <p className="mt-1 text-xs leading-5 text-zinc-500">
                        可上传多个 PDF/DOCX；系统将解析内容并与主合同进行深度比对。
                      </p>
                    </div>
                    <button
                      className="inline-flex h-9 items-center gap-2 rounded-md border border-zinc-300 bg-white px-3 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#214a4b]/30"
                      onClick={() => relatedFilesInputRef.current?.click()}
                      type="button"
                    >
                      <Upload aria-hidden="true" className="h-4 w-4" />
                      选择关联文件
                    </button>
                    <input
                      accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                      className="hidden"
                      multiple
                      onChange={(event) =>
                        handleRelatedFilesSelect(Array.from(event.target.files ?? []))
                      }
                      ref={relatedFilesInputRef}
                      type="file"
                    />
                  </div>

                  {form.relatedFiles.length ? (
                    <div className="mt-3 space-y-2">
                      {form.relatedFiles.map((file, index) => (
                        <div
                          className="flex items-center justify-between gap-3 rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2"
                          key={`${file.name}-${file.size}-${file.lastModified}`}
                        >
                          <div className="flex min-w-0 items-center gap-2">
                            <FileText
                              aria-hidden="true"
                              className="h-4 w-4 shrink-0 text-[#214a4b]"
                            />
                            <div className="min-w-0">
                              <p className="truncate text-sm text-zinc-700">{file.name}</p>
                              <p className="text-xs text-zinc-500">{formatFileSize(file.size)}</p>
                            </div>
                          </div>
                          <button
                            className="shrink-0 rounded-md px-2 py-1 text-xs text-zinc-500 transition-colors hover:bg-white hover:text-zinc-900"
                            onClick={() => removeRelatedFile(index)}
                            type="button"
                          >
                            删除
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {relatedFilesError ? (
                    <p className="mt-2 flex items-center gap-2 text-sm text-rose-700">
                      <AlertTriangle aria-hidden="true" className="h-4 w-4" />
                      {relatedFilesError}
                    </p>
                  ) : null}
                </section>
              </div>
            ) : null}

            <div className="flex flex-col gap-3 border-t border-zinc-200 pt-5 sm:flex-row sm:items-center sm:justify-end">
              <button
                className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-[#214a4b] px-5 text-sm font-semibold text-white transition-colors hover:bg-[#183c3d] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#214a4b] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-zinc-300"
                disabled={isSubmitting}
                type="submit"
              >
                {isSubmitting ? (
                  <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                ) : (
                  <Send aria-hidden="true" className="h-4 w-4" />
                )}
                {isSubmitting ? "正在分析" : activeModule.submitLabel}
              </button>
            </div>
          </form>
        </section>

        <AnalysisResultPanel error={error} isSubmitting={isSubmitting} result={result} />
      </div>
    </main>
  );
}

function AnalysisResultPanel({
  error,
  isSubmitting,
  result,
}: {
  error: string | null;
  isSubmitting: boolean;
  result: LegalAnalysisResponse | null;
}) {
  return (
    <aside className="rounded-lg border border-zinc-200 bg-white p-6 shadow-sm lg:min-h-[calc(100vh-2rem)]">
      <div className="flex items-center justify-between border-b border-zinc-200 pb-5">
        <h2 className="text-lg font-semibold tracking-tight text-zinc-900">分析结果</h2>
        <FileText aria-hidden="true" className="h-5 w-5 text-[#214a4b]" />
      </div>

      {isSubmitting ? <LoadingState /> : null}
      {!isSubmitting && error ? <ErrorState message={error} /> : null}
      {!isSubmitting && !error && result ? <ResultState result={result} /> : null}
      {!isSubmitting && !error && !result ? <EmptyState /> : null}
    </aside>
  );
}

function LoadingState() {
  return (
    <div className="mt-6 flex min-h-[420px] flex-col items-center justify-center px-6 text-center">
      <Loader2 aria-hidden="true" className="h-8 w-8 animate-spin text-[#214a4b]" />
      <p className="mt-4 text-sm font-medium text-zinc-900">正在生成分析结果</p>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="mt-6 rounded-lg border border-rose-200 bg-rose-50 p-4 text-rose-900">
      <div className="flex items-start gap-3">
        <AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0" />
        <div>
          <p className="text-sm font-semibold">分析失败</p>
          <p className="mt-2 text-sm leading-6">{message}</p>
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="mt-6 flex min-h-[420px] items-center justify-center px-6 text-center">
      <p className="text-sm leading-6 text-zinc-500">
        提交合同或案件事实后，这里展示结构化分析结果。
      </p>
    </div>
  );
}

function ResultState({ result }: { result: LegalAnalysisResponse }) {
  if (isContractReviewReportResponse(result)) {
    return <ContractReviewReportResult result={result} />;
  }

  if (isContractBackgroundResponse(result)) {
    return <ContractBackgroundResult result={result} />;
  }

  return <ClassicAnalysisResult result={result} />;
}

function ClassicAnalysisResult({ result }: { result: CaseAnalysisResponse }) {
  return (
    <div className="mt-6 space-y-5">
      <div
        className={cn(
          "inline-flex rounded-md border px-3 py-1.5 text-sm font-semibold",
          RISK_STYLES[result.risk_level],
        )}
      >
        {RISK_LABELS[result.risk_level]}
      </div>

      <section>
        <h3 className="text-sm font-semibold text-zinc-900">摘要</h3>
        <p className="mt-2 text-sm leading-6 text-zinc-600">{result.summary}</p>
      </section>

      <ResultList title="主要发现" items={result.findings} />
      <ResultList title="处理建议" items={result.suggestions} />

      <Disclaimer text={result.disclaimer} />
    </div>
  );
}

function ContractBackgroundResult({ result }: { result: ContractBackgroundResponse }) {
  return (
    <div className="mt-6 space-y-5">
      <div className="inline-flex items-center gap-2 rounded-md border border-[#b9d8cc] bg-[#eef8f2] px-3 py-1.5 text-sm font-semibold text-[#214a4b]">
        <Tags aria-hidden="true" className="h-4 w-4" />
        {CATEGORY_LABELS[result.contract_category]}
      </div>

      <section>
        <h3 className="text-sm font-semibold text-zinc-900">6个基础问题</h3>
        <div className="mt-3 grid gap-3">
          {BACKGROUND_FIELDS.map((field) => {
            const value = result.background_card[field.key];
            return (
              <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-3" key={field.key}>
                <p className="text-xs font-semibold text-zinc-500">{field.label}</p>
                <p className="mt-1 text-sm leading-6 text-zinc-700">
                  {value.text || "暂未从合同文本确认"}
                </p>
                <SourceRefs refs={value.source_refs} />
              </div>
            );
          })}
        </div>
      </section>

      <RelatedDocuments documents={result.related_documents} />
      <Pitfalls pitfalls={result.pitfalls} />
      <Disclaimer text={result.disclaimer} />
    </div>
  );
}

function RelatedDocuments({
  documents,
}: {
  documents: ContractBackgroundResponse["related_documents"];
}) {
  return (
    <section>
      <h3 className="text-sm font-semibold text-zinc-900">关联文件</h3>
      {documents.length ? (
        <div className="mt-3 space-y-3">
          {documents.map((document, index) => (
            <div
              className="rounded-lg border border-zinc-200 bg-white p-3"
              key={`${document.name}-${index}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium text-zinc-900">
                  {RELATED_DOC_NAME_MAP[document.name] ?? document.name}
                </p>
                <span
                  className={cn(
                    "rounded-md border px-2 py-1 text-xs font-semibold",
                    RELATED_STATUS_STYLES[document.status],
                  )}
                >
                  {RELATED_STATUS_LABELS[document.status]}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-sm leading-6 text-zinc-500">暂无关联文件提示。</p>
      )}
    </section>
  );
}

function Pitfalls({ pitfalls }: { pitfalls: ContractBackgroundResponse["pitfalls"] }) {
  return (
    <section>
      <div className="flex items-center gap-2">
        <ListChecks aria-hidden="true" className="h-4 w-4 text-[#214a4b]" />
        <h3 className="text-sm font-semibold text-zinc-900">审查陷阱</h3>
      </div>
      {pitfalls.length ? (
        <div className="mt-3 space-y-3">
          {pitfalls.map((pitfall, index) => (
            <div className="rounded-lg border border-zinc-200 bg-white p-3" key={`${pitfall.name}-${index}`}>
              <p className="text-sm font-medium text-zinc-900">
                {PITFALL_NAME_MAP[pitfall.name] ?? pitfall.name}
              </p>
              <p className="mt-2 text-sm leading-6 text-zinc-600">{pitfall.risk}</p>
              <p className="mt-2 text-sm leading-6 text-zinc-700">{pitfall.review_action}</p>
              <SourceRefs refs={pitfall.source_refs} />
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-sm leading-6 text-zinc-500">暂无特别陷阱提示。</p>
      )}
    </section>
  );
}

function SourceRefs({ refs }: { refs: SourceRef[] }) {
  if (!refs.length) return null;

  return (
    <div className="mt-2 space-y-2">
      {refs.map((ref) => (
        <details
          className="rounded-md border border-zinc-200 bg-white px-3 py-2"
          key={ref.paragraph_id}
        >
          <summary className="cursor-pointer text-xs font-medium leading-5 text-zinc-600">
            来源：{ref.clause_path ? `${ref.clause_path} · ` : ""}
            {formatParagraphRef(ref.paragraph_id)}
          </summary>
          <p className="mt-2 whitespace-pre-wrap break-words border-t border-zinc-100 pt-2 text-xs leading-5 text-zinc-500">
            {ref.quote}
          </p>
        </details>
      ))}
    </div>
  );
}

function formatParagraphRef(paragraphId: string) {
  const number = Number(paragraphId.replace(/^p0*/i, ""));
  if (!Number.isFinite(number) || number <= 0) return paragraphId;
  return `第${number}段`;
}

function Disclaimer({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-[#f7f8f6] p-4">
      <div className="flex gap-2">
        <Info aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-[#214a4b]" />
        <p className="text-xs leading-5 text-zinc-500">{text}</p>
      </div>
    </div>
  );
}

function ResultList({
  fallback = "暂无内容。",
  items,
  title,
}: {
  fallback?: string;
  items: string[];
  title: string;
}) {
  return (
    <section>
      <h3 className="text-sm font-semibold text-zinc-900">{title}</h3>
      {items.length ? (
        <ul className="mt-3 space-y-3">
          {items.map((item, index) => (
            <li className="flex gap-3 text-sm leading-6 text-zinc-600" key={`${title}-${index}`}>
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[#214a4b]" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm leading-6 text-zinc-500">{fallback}</p>
      )}
    </section>
  );
}
