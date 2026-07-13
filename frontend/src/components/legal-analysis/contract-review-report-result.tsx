import { AlertTriangle, FileWarning, Scale } from "lucide-react";

import type { ContractReviewReportResponse } from "@/lib/legal-analysis-types";

import { ContractReviewDocumentCard } from "./contract-review-document-card";

export function ContractReviewReportResult({
  result,
}: {
  result: ContractReviewReportResponse;
}) {
  const isPartial = result.status === "partial";

  return (
    <div className="mt-6 space-y-4">
      {isPartial ? (
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
        <ContractReviewDocumentCard document={result.report_document} isPartial={isPartial} />
      ) : (
        <section className="relative overflow-hidden rounded-lg border border-zinc-200 bg-white p-4 pl-5">
          <div aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-zinc-300" />
          <div className="flex items-start gap-3">
            <FileWarning aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-zinc-500" />
            <div>
              <h3 className="text-sm font-semibold text-zinc-900">PDF 审查报告</h3>
              <p className="mt-1 text-sm leading-6 text-zinc-600">
                PDF 报告文件暂不可用，请重新发起审查。
              </p>
            </div>
          </div>
        </section>
      )}

      <div className="flex items-start gap-2 border-t border-zinc-200 pt-4 text-xs leading-5 text-zinc-500">
        <Scale aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-[#214a4b]" />
        <p>下载后的报告仍须由法律专业人士结合完整材料复核。</p>
      </div>
    </div>
  );
}
