import { proxyBackendPost } from "@/lib/backend-proxy";

export async function POST(request: Request) {
  return proxyBackendPost(request, "/api/v1/contract-review-reports");
}
