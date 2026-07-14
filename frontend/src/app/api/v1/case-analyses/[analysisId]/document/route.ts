import { proxyBackendDownload } from "@/lib/backend-proxy";

export async function GET(
  _request: Request,
  context: { params: Promise<{ analysisId: string }> },
) {
  const { analysisId } = await context.params;
  return proxyBackendDownload(
    `/api/v1/case-analyses/${encodeURIComponent(analysisId)}/document`,
  );
}
