export type DetectedTable = {
  id: string;
  name: string;
  sheet_name: string;
  row_count: number;
  columns: { name: string; path: string[]; dtype: string }[];
  hierarchy: { levels: number; columns: unknown[] };
  sample_rows: Record<string, string>[];
  region: string;
};

export type UploadQuestion = {
  id: string;
  table_id: string | null;
  question_type: string;
  question: string;
  required: boolean;
  prefill?: string;
  context?: Record<string, unknown>;
};

// prefill is used by upload Q&A to suggest answers from detected headers

export type UploadResponse = {
  session_id: string;
  filename: string;
  description: string;
  status: string;
  detected_tables: DetectedTable[];
  table_count: number;
  questions: UploadQuestion[];
};

export type QuerySource = {
  table_id: string;
  table_name: string;
  sheet_name: string;
  column: string;
  row_index: number;
  value: unknown;
  matched_region: string;
  evidence: Record<string, unknown>;
};

export type QueryResponse = {
  question: string;
  answer: string;
  value: unknown;
  unit: string | null;
  reasoning: string;
  sql_equivalent: string | null;
  sources: QuerySource[];
};

const API_BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new Error(
      "无法连接后端（127.0.0.1:8000）。请先启动后端：在 web/backend 运行 uvicorn app.main:app --reload --port 8000",
    );
  }

  // Response body can only be read once — always read as text, then parse JSON.
  const raw = await resp.text();
  let data: unknown = null;
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      data = null;
    }
  }

  if (!resp.ok) {
    if (resp.status === 502 || resp.status === 503 || resp.status === 504) {
      throw new Error("后端未启动或已崩溃。请先启动后端服务（端口 8000）。");
    }
    const detail =
      data && typeof data === "object" && data !== null && "detail" in data
        ? typeof (data as { detail: unknown }).detail === "string"
          ? (data as { detail: string }).detail
          : JSON.stringify((data as { detail: unknown }).detail)
        : raw || `请求失败: ${resp.status}`;
    throw new Error(detail);
  }

  if (data === null) {
    throw new Error(raw ? "服务器返回了无法解析的响应" : "服务器返回空响应");
  }
  return data as T;
}

export async function uploadFile(file: File, description: string): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("description", description);
  return request<UploadResponse>("/upload", { method: "POST", body: form });
}

export async function submitQA(
  sessionId: string,
  answers: { question_id: string; question: string; answer: string; table_id?: string | null; question_type?: string }[],
) {
  return request(`/sessions/${sessionId}/qa`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      answers: answers.map((a) => ({
        question_id: a.question_id,
        question: a.question,
        answer: a.answer,
        table_id: a.table_id ?? null,
        question_type: a.question_type ?? "general",
      })),
    }),
  });
}

export async function queryData(question: string, sessionId?: string, useLlm = false): Promise<QueryResponse> {
  return request<QueryResponse>("/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId ?? null, use_llm: useLlm }),
  });
}

export async function listSessions() {
  return request<
    { id: string; filename: string; description: string; status: string; table_count: number; created_at: string }[]
  >("/sessions");
}

export async function listTables() {
  return request<DetectedTable[]>("/tables");
}
