import { NextResponse } from "next/server";

const DEFAULT_BACKEND_API_BASE_URL = "http://127.0.0.1:8000";
const DEFAULT_PROXY_ERROR_MESSAGE = "分析服务暂时不可用，请稍后重试。";

type BackendErrorPayload = {
  error?: {
    code?: string;
    message?: string;
  };
};

export async function proxyBackendPost(request: Request, path: string): Promise<NextResponse> {
  const started = Date.now();
  const backendBaseUrl =
    process.env.BACKEND_API_BASE_URL?.replace(/\/$/, "") || DEFAULT_BACKEND_API_BASE_URL;

  const contentType = request.headers.get("Content-Type") || "";
  const isMultipart = contentType.toLowerCase().includes("multipart/form-data");
  console.info(
    `[backend-proxy] request path=${path} mode=${isMultipart ? "multipart" : "json"}`,
  );

  let requestBody: BodyInit | null;
  const requestHeaders: Record<string, string> = {};

  if (isMultipart) {
    try {
      requestBody = await request.formData();
    } catch {
      return NextResponse.json(
        { error: { code: "invalid_form_data", message: "上传表单内容无效。" } },
        { status: 400 },
      );
    }
  } else {
    let requestBodyJson: unknown;
    try {
      requestBodyJson = await request.json();
    } catch {
      return NextResponse.json(
        { error: { code: "invalid_json", message: "请求内容不是有效的 JSON。" } },
        { status: 400 },
      );
    }
    requestBody = JSON.stringify(requestBodyJson);
    requestHeaders["Content-Type"] = "application/json";
  }

  try {
    const backendResponse = await fetch(`${backendBaseUrl}${path}`, {
      method: "POST",
      headers: requestHeaders,
      body: requestBody,
      cache: "no-store",
    });

    const data = (await backendResponse.json().catch(() => null)) as BackendErrorPayload | null;

    if (!backendResponse.ok) {
      console.warn(
        `[backend-proxy] backend_error path=${path} status=${backendResponse.status} elapsed_ms=${
          Date.now() - started
        }`,
      );
      return NextResponse.json(
        {
          error: {
            code: data?.error?.code || "backend_error",
            message: data?.error?.message || DEFAULT_PROXY_ERROR_MESSAGE,
          },
        },
        { status: backendResponse.status },
      );
    }

    console.info(
      `[backend-proxy] completed path=${path} status=${backendResponse.status} elapsed_ms=${
        Date.now() - started
      }`,
    );
    return NextResponse.json(data, { status: backendResponse.status });
  } catch {
    console.error(
      `[backend-proxy] backend_unavailable path=${path} elapsed_ms=${Date.now() - started}`,
    );
    return NextResponse.json(
      {
        error: {
          code: "backend_unavailable",
          message: DEFAULT_PROXY_ERROR_MESSAGE,
        },
      },
      { status: 503 },
    );
  }
}

const DOWNLOAD_RESPONSE_HEADERS = [
  "Content-Disposition",
  "Content-Type",
  "Content-Length",
  "ETag",
  "Cache-Control",
  "X-Content-Type-Options",
] as const;

export async function proxyBackendDownload(path: string): Promise<Response> {
  const started = Date.now();
  const backendBaseUrl =
    process.env.BACKEND_API_BASE_URL?.replace(/\/$/, "") || DEFAULT_BACKEND_API_BASE_URL;

  try {
    const backendResponse = await fetch(`${backendBaseUrl}${path}`, {
      method: "GET",
      cache: "no-store",
    });

    if (!backendResponse.ok) {
      const data = (await backendResponse.json().catch(() => null)) as BackendErrorPayload | null;
      console.warn(
        `[backend-proxy] backend_download_error path=${path} status=${backendResponse.status} elapsed_ms=${
          Date.now() - started
        }`,
      );
      return NextResponse.json(
        {
          error: {
            code: data?.error?.code || "backend_error",
            message: data?.error?.message || DEFAULT_PROXY_ERROR_MESSAGE,
          },
        },
        { status: backendResponse.status },
      );
    }

    const headers = new Headers();
    DOWNLOAD_RESPONSE_HEADERS.forEach((name) => {
      const value = backendResponse.headers.get(name);
      if (value) headers.set(name, value);
    });
    console.info(
      `[backend-proxy] download_completed path=${path} status=${backendResponse.status} elapsed_ms=${
        Date.now() - started
      }`,
    );
    // 直接转发响应流，避免 Next.js 服务端额外复制完整 PDF。
    return new Response(backendResponse.body, {
      status: backendResponse.status,
      headers,
    });
  } catch {
    console.error(
      `[backend-proxy] backend_download_unavailable path=${path} elapsed_ms=${Date.now() - started}`,
    );
    return NextResponse.json(
      {
        error: {
          code: "backend_unavailable",
          message: DEFAULT_PROXY_ERROR_MESSAGE,
        },
      },
      { status: 503 },
    );
  }
}
