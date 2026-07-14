import { proxyBackendGet } from "@/lib/backend-proxy";

export async function GET(
  _request: Request,
  context: { params: Promise<{ taskId: string }> },
) {
  const { taskId } = await context.params;
  return proxyBackendGet(`/api/v1/contract-review-reports/${encodeURIComponent(taskId)}`);
}
