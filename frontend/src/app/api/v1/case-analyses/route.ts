import { proxyBackendGet, proxyBackendPost } from "@/lib/backend-proxy";

export async function GET() {
  return proxyBackendGet("/api/v1/case-analyses");
}

export async function POST(request: Request) {
  return proxyBackendPost(request, "/api/v1/case-analyses");
}
