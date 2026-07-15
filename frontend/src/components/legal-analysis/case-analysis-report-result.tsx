import { AlertTriangle, Download, FileText } from "lucide-react";

import type { CaseAnalysisResponse } from "@/lib/legal-analysis-types";

export function CaseAnalysisReportResult({ result }: { result: CaseAnalysisResponse }) {
  return (
    <div className="mt-6 min-w-0 space-y-4 [overflow-wrap:anywhere]">
      {result.status === "partial" ? (
        <div className="flex min-w-0 items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-950">
          <AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0" />
          <div className="min-w-0">
            <p className="text-sm font-semibold">当前文书基于不完整材料生成</p>
            <p className="mt-1 text-xs leading-5">
              文件不可直接提交或作为诉讼决策依据，请补充材料并交由专业律师复核。
            </p>
          </div>
        </div>
      ) : null}

      <section className="min-w-0 rounded-xl border border-[#b9d8cc] bg-[#f4faf6] p-5">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#214a4b] text-white">
            <FileText aria-hidden="true" className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-zinc-950">案件文书 PDF 已生成</h3>
            <p className="mt-1 text-xs leading-5 text-zinc-600">
              文书包含精简处理方案、草稿要点和律师复核提示。
            </p>
            {result.draft_document ? (
              <a
                className="mt-4 inline-flex h-10 max-w-full items-center gap-2 rounded-md bg-[#214a4b] px-4 text-sm font-semibold text-white transition-colors hover:bg-[#183c3d] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#214a4b]/35 focus-visible:ring-offset-2"
                href={result.draft_document.download_path}
              >
                <Download aria-hidden="true" className="h-4 w-4 shrink-0" />
                <span className="truncate">下载案件文书 PDF</span>
              </a>
            ) : (
              <p className="mt-4 text-xs font-medium text-rose-700">
                文件元数据暂不可用，请重新生成。
              </p>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
