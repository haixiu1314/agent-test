import axios from "axios";

export interface Project {
  id: string;
  name: string;
  description: string;
  business_type: string;
  created_at: string;
  updated_at: string;
}
export interface Agent {
  id: string;
  project_id: string;
  name: string;
  kind: "http" | "python";
  endpoint: string;
  method: "POST" | "GET";
  request_template: Record<string, unknown>;
  input_field: string;
  output_field: string;
  history_field: string | null;
  trace_field: string | null;
  usage_field: string | null;
  contexts_field: string | null;
  timeout_seconds: number;
  retries: number;
  version: number;
  version_label: string;
  adapter_name: string;
  auth_header: string;
  has_api_key: boolean;
  header_names: string[];
}
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export const api = axios.create({ baseURL: "/api/v1", timeout: 260000 });
api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem("atl_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (
      error.response?.status === 401 &&
      !error.config?.url?.startsWith("/auth/")
    ) {
      sessionStorage.removeItem("atl_token");
      window.location.assign("/login");
    }
    return Promise.reject(error);
  },
);
export function message(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data;
    return data?.error?.message
      ? `${data.error.message}${data.request_id ? `（请求 ${data.request_id.slice(0, 8)}）` : ""}`
      : "暂时无法连接服务，请检查后端并重试";
  }
  return error instanceof Error ? error.message : "操作失败，请重试";
}
