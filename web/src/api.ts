export type ConfigItem = {
  key: string;
  label: string;
  help?: string;
  type: "string" | "secret" | "number" | "bool" | "list" | "path";
  required?: boolean;
};

export type ConfigSection = {
  id: string;
  title: string;
  description?: string;
  items: ConfigItem[];
};

export type ConfigValue = string | number | boolean | null | { isSet: boolean; value: string };
export type StringMap<T> = { [key: string]: T };
export type ConfigValues = StringMap<ConfigValue>;

export type ConfigResponse = {
  sections: ConfigSection[];
  values: ConfigValues;
  envFileExists: boolean;
  envUpdatedAt: string | null;
};

export type ReportMeta = {
  path: string;
  title: string;
  type: "dashboard" | "daily" | "review" | "other";
  date: string | null;
  updated_at: string;
  size: number;
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function request<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchReports(): Promise<{ reports: ReportMeta[] }> {
  return request(`${API_BASE}/api/reports`);
}

export async function fetchReport(path: string): Promise<{ path: string; content: string }> {
  const query = new URLSearchParams({ path });
  return request(`${API_BASE}/api/report?${query.toString()}`);
}

export async function fetchConfig(): Promise<ConfigResponse> {
  return request(`${API_BASE}/api/config`);
}

export async function saveConfig(
  values: ConfigValues,
  clearSecrets: string[] = [],
): Promise<void> {
  await request(`${API_BASE}/api/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values, clearSecrets }),
  });
}

export type RunMode = "full" | "market-review" | "schedule";
export type RunRecord = {
  id: string;
  mode: RunMode;
  command: string;
  pid: number;
  startedAt: string;
  status: string;
  exitCode?: number;
  logLines?: number;
  lastLine?: string;
};

export async function runJob(mode: RunMode): Promise<{ run: RunRecord }> {
  return request(`${API_BASE}/api/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
}

export type RunLogLine = { ts: string; line: string };

export async function fetchRuns(): Promise<{ runs: RunRecord[] }> {
  return request(`${API_BASE}/api/run`);
}

export async function fetchRunLogs(
  id: string,
  cursor = 0,
): Promise<{ logs: RunLogLine[]; nextCursor: number; status: string; exitCode?: number }> {
  const query = new URLSearchParams({ id, cursor: cursor.toString() });
  return request(`${API_BASE}/api/run/logs?${query.toString()}`);
}
