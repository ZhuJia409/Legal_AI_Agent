import type { ApiErrorResponse, LegalAnalysisRequest, LegalAnalysisResponse } from "./legal-analysis-types";

export type LegalAnalysisEndpoint = "case-analyses" | "contract-reviews";

const DEFAULT_ERROR_MESSAGE = "分析服务暂时不可用，请稍后重试。";

export async function submitLegalAnalysis(
  endpoint: LegalAnalysisEndpoint,
  payload: LegalAnalysisRequest,
): Promise<LegalAnalysisResponse> {
  let requestInit: RequestInit;

  if (payload.file) {
    const formData = new FormData();
    if (payload.title) {
      formData.append("title", payload.title);
    }
    formData.append("file", payload.file);
    payload.relatedFiles?.forEach((relatedFile) => {
      formData.append("related_files", relatedFile);
    });
    requestInit = {
      method: "POST",
      body: formData,
    };
  } else {
    requestInit = {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ title: payload.title, content: payload.content }),
    };
  }

  const response = await fetch(`/api/v1/${endpoint}`, requestInit);

  const data = (await response.json().catch(() => null)) as
    | LegalAnalysisResponse
    | ApiErrorResponse
    | null;

  if (!response.ok) {
    const message = data && "error" in data ? data.error?.message : null;
    throw new Error(message || DEFAULT_ERROR_MESSAGE);
  }

  return data as LegalAnalysisResponse;
}
