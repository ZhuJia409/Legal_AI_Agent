"use client";

import { AlertCircle, Download, FileCheck2, Loader2 } from "lucide-react";
import { useState } from "react";

import type { ApiErrorResponse, ReportDocumentInfo } from "@/lib/legal-analysis-types";
import { cn } from "@/lib/utils";

type DownloadState = "idle" | "downloading" | "error";

export function ContractReviewDocumentCard({
  document,
  isPartial,
}: {
  document: ReportDocumentInfo;
  isPartial: boolean;
}) {
  const [downloadState, setDownloadState] = useState<DownloadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleDownload() {
    if (downloadState === "downloading") return;
    setDownloadState("downloading");
    setErrorMessage(null);

    try {
      const response = await fetch(document.download_path, { cache: "no-store" });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as ApiErrorResponse | null;
        throw new Error(payload?.error?.message || "PDF 报告下载失败，请稍后重试。");
      }

      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = window.document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = document.filename;
      anchor.click();
      URL.revokeObjectURL(objectUrl);
      setDownloadState("idle");
    } catch (error) {
      setDownloadState("error");
      setErrorMessage(error instanceof Error ? error.message : "PDF 报告下载失败，请稍后重试。");
    }
  }

  return (
    <section
      className={cn(
        "relative overflow-hidden rounded-lg border bg-white p-4 pl-5",
        isPartial ? "border-rose-200" : "border-[#b9d8cc]",
      )}
      aria-labelledby="contract-review-document-title"
    >
      <div
        aria-hidden="true"
        className={cn(
          "absolute inset-y-0 left-0 w-1",
          isPartial ? "bg-rose-500" : "bg-[#214a4b]",
        )}
      />
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <FileCheck2
              aria-hidden="true"
              className={cn("h-4 w-4 shrink-0", isPartial ? "text-rose-700" : "text-[#214a4b]")}
            />
            <h3 id="contract-review-document-title" className="text-sm font-semibold text-zinc-900">
              PDF 审查报告
            </h3>
          </div>
          <p className="mt-2 break-words text-sm font-medium text-zinc-700">{document.filename}</p>
          <p className="mt-1 text-xs leading-5 text-zinc-500">
            {formatFileSize(document.size_bytes)} · {formatGeneratedAt(document.generated_at)}
          </p>
          {isPartial ? (
            <p className="mt-2 text-xs font-medium leading-5 text-rose-700">
              不完整报告，不可作为签署依据。
            </p>
          ) : null}
        </div>

        <button
          type="button"
          onClick={handleDownload}
          disabled={downloadState === "downloading"}
          className={cn(
            "inline-flex min-h-10 shrink-0 items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#214a4b] focus-visible:ring-offset-2",
            "disabled:cursor-not-allowed disabled:opacity-60",
            isPartial
              ? "bg-rose-700 text-white hover:bg-rose-800"
              : "bg-[#214a4b] text-white hover:bg-[#173839]",
          )}
        >
          {downloadState === "downloading" ? (
            <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin motion-reduce:animate-none" />
          ) : (
            <Download aria-hidden="true" className="h-4 w-4" />
          )}
          {downloadState === "downloading"
            ? "正在下载"
            : downloadState === "error"
              ? "重试下载"
              : "下载 PDF"}
        </button>
      </div>

      {errorMessage ? (
        <div className="mt-3 flex items-start gap-2 border-t border-rose-100 pt-3 text-xs leading-5 text-rose-700" role="alert">
          <AlertCircle aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{errorMessage}</span>
        </div>
      ) : null}
    </section>
  );
}

function formatFileSize(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatGeneratedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "生成时间待确认";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(date);
}
