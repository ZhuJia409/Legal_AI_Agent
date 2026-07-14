"use client";

import { AlertTriangle, FileClock, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import {
  fetchAnalysisHistory,
  fetchAnalysisHistoryDetail,
} from "@/lib/legal-analysis-api";
import type {
  AnalysisHistoryItem,
  LegalAnalysisResponse,
} from "@/lib/legal-analysis-types";

type HistoryEndpoint = "case-analyses" | "contract-review-reports";

export function AnalysisHistory({
  endpoint,
  onOpen,
}: {
  endpoint: HistoryEndpoint;
  onOpen: (result: LegalAnalysisResponse) => void;
}) {
  const [items, setItems] = useState<AnalysisHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchAnalysisHistory(endpoint)
      .then((response) => {
        if (active) setItems(response.items);
      })
      .catch((historyError: unknown) => {
        if (active) {
          setError(historyError instanceof Error ? historyError.message : "历史记录加载失败。");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [endpoint]);

  async function openItem(item: AnalysisHistoryItem) {
    const id = item.analysis_id ?? item.task_id;
    if (!id) return;
    setOpeningId(id);
    setError(null);
    try {
      onOpen(await fetchAnalysisHistoryDetail(endpoint, id));
    } catch (detailError) {
      setError(detailError instanceof Error ? detailError.message : "历史详情加载失败。");
    } finally {
      setOpeningId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-72 items-center justify-center gap-3 text-sm text-zinc-600">
        <Loader2 className="h-5 w-5 animate-spin" />
        正在加载历史记录
      </div>
    );
  }

  return (
    <div className="mt-6 space-y-4">
      {error ? (
        <div className="flex gap-2 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      ) : null}
      {!items.length ? (
        <div className="flex min-h-72 flex-col items-center justify-center text-center text-zinc-500">
          <FileClock className="h-8 w-8" />
          <p className="mt-3 text-sm">暂无历史记录。</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {items.map((item) => {
            const id = item.analysis_id ?? item.task_id ?? "";
            return (
              <article
                className="flex min-w-0 flex-col gap-3 rounded-lg border border-zinc-200 bg-zinc-50 p-4 sm:flex-row sm:items-center sm:justify-between"
                key={id}
              >
                <div className="min-w-0">
                  <h2 className="break-words text-sm font-semibold text-zinc-900">
                    {item.title || "未命名记录"}
                  </h2>
                  <p className="mt-1 text-xs text-zinc-500">
                    {new Date(item.created_at).toLocaleString("zh-CN")}
                    {" · "}{item.status === "partial" ? "部分完成" : "已完成"}
                    {" · 风险："}{item.risk_level}
                  </p>
                </div>
                <button
                  className="h-9 shrink-0 rounded-md bg-[#214a4b] px-4 text-sm font-semibold text-white disabled:bg-zinc-300"
                  disabled={openingId === id}
                  onClick={() => openItem(item)}
                  type="button"
                >
                  {openingId === id ? "加载中" : "查看"}
                </button>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
