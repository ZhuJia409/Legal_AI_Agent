import { proxyBackendDownload } from "@/lib/backend-proxy";

export async function GET(
  _request: Request,
  context: { params: Promise<{ taskId: string }> },
) {
  const { taskId } = await context.params;
  const encodedTaskId = encodeURIComponent(taskId);
  return proxyBackendDownload(
    `/api/v1/contract-review-reports/${encodedTaskId}/document`,
  );
}
