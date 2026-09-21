export type QueryValue = string | number | boolean | Array<string | number> | undefined;

export class CanvasApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "CanvasApiError";
  }
}

export interface RequestOptions {
  query?: Record<string, QueryValue>;
  body?: unknown;
}

export class CanvasClient {
  constructor(
    private readonly baseUrl: string,
    private readonly accessToken: string,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  async request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    if (!path.startsWith("/api/v1/")) throw new Error("Canvas paths must begin with /api/v1/");
    const url = new URL(path, this.baseUrl);

    for (const [key, raw] of Object.entries(options.query || {})) {
      if (raw === undefined) continue;
      const values = Array.isArray(raw) ? raw : [raw];
      for (const value of values) url.searchParams.append(key, String(value));
    }

    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.accessToken}`,
      Accept: "application/json",
    };
    let body: string | undefined;
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.body);
    }

    const response = await this.fetchImpl(url, { method, headers, body, redirect: "follow" });
    const text = await response.text();
    let payload: unknown = undefined;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = { message: text.slice(0, 500) };
      }
    }

    if (!response.ok) {
      const message = extractErrorMessage(payload) || `Canvas request failed with HTTP ${response.status}`;
      throw new CanvasApiError(message, response.status, payload);
    }
    return payload as T;
  }

  async uploadSubmissionFile(input: {
    courseId: string;
    assignmentId: string;
    userId: string;
    fileName: string;
    contentType: string;
    contentBase64: string;
  }): Promise<unknown> {
    const bytes = Buffer.from(input.contentBase64, "base64");
    if (bytes.byteLength === 0) throw new Error("The uploaded file is empty");
    if (bytes.byteLength > 10 * 1024 * 1024) throw new Error("Files are limited to 10 MB in this MCP");

    const init = await this.request<{ upload_url: string; upload_params: Record<string, string> }>(
      "POST",
      `/api/v1/courses/${encodeURIComponent(input.courseId)}/assignments/${encodeURIComponent(input.assignmentId)}/submissions/${encodeURIComponent(input.userId)}/files`,
      {
        body: {
          name: input.fileName,
          size: bytes.byteLength,
          content_type: input.contentType,
        },
      },
    );

    const uploadUrl = new URL(init.upload_url);
    if (uploadUrl.protocol !== "https:") throw new Error("Canvas returned a non-HTTPS upload URL");

    const form = new FormData();
    for (const [key, value] of Object.entries(init.upload_params)) form.append(key, value);
    form.append("file", new Blob([bytes], { type: input.contentType }), input.fileName);

    const response = await this.fetchImpl(uploadUrl, { method: "POST", body: form, redirect: "follow" });
    const text = await response.text();
    let payload: unknown;
    try {
      payload = text ? JSON.parse(text) : undefined;
    } catch {
      payload = { message: text.slice(0, 500) };
    }
    if (!response.ok) throw new CanvasApiError("Canvas file upload failed", response.status, payload);
    return payload;
  }
}

function extractErrorMessage(payload: unknown): string | undefined {
  if (!payload || typeof payload !== "object") return undefined;
  const object = payload as Record<string, unknown>;
  if (typeof object.message === "string") return object.message;
  if (Array.isArray(object.errors) && object.errors.length > 0) {
    const first = object.errors[0];
    if (typeof first === "string") return first;
    if (first && typeof first === "object" && typeof (first as Record<string, unknown>).message === "string") {
      return (first as Record<string, unknown>).message as string;
    }
  }
  return undefined;
}
