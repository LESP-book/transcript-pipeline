export interface ConfigResponse {
  profiles: string[];
  backends: string[];
  configured_backends: string[];
  active_profile: string;
}

export interface FileItem {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
}

export interface FileListResponse {
  current_path: string;
  parent_path: string | null;
  items: FileItem[];
}

export interface JobState {
  id: string;
  kind: string;
  status: string;
  created_at: string;
  updated_at: string;
  current_stage: string;
  error_message: string;
  output_path: string;
  total?: number;
  success?: number;
  failed?: number;
  items?: Array<Record<string, unknown>>;
}

export interface JobListResponse {
  items: JobState[];
}

export interface SingleJobPayload {
  video: string;
  reference: string;
  output_dir: string;
  profile?: string | null;
  backend?: string | null;
  config?: string | null;
  book_name?: string | null;
  chapter?: string | null;
  glossary_file?: string | null;
}

export interface BatchJobPayload {
  manifest?: string | null;
  videos_dir?: string | null;
  reference_dir?: string | null;
  shared_reference?: string | null;
  output_dir?: string | null;
  profile?: string | null;
  backend?: string | null;
  config?: string | null;
  remote_concurrency: number;
  book_name?: string | null;
  chapter?: string | null;
  glossary_file?: string | null;
}

export interface StageRunPayload {
  profile?: string | null;
  backend?: string | null;
  config?: string | null;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

function buildQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `?${query}` : "";
}

export function getConfig(): Promise<ConfigResponse> {
  return requestJson<ConfigResponse>("/api/config");
}

export function listFs(path: string | null, type: "file" | "dir" | "all", showHidden: boolean): Promise<FileListResponse> {
  return requestJson<FileListResponse>(`/api/fs/list${buildQuery({ path, type, show_hidden: showHidden })}`);
}

export function submitJob(payload: SingleJobPayload): Promise<{ job_id: string }> {
  return requestJson<{ job_id: string }>("/api/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getJob(jobId: string): Promise<JobState> {
  return requestJson<JobState>(`/api/jobs/${jobId}`);
}

export function listJobs(): Promise<JobListResponse> {
  return requestJson<JobListResponse>("/api/jobs");
}

export function submitBatchJob(payload: BatchJobPayload): Promise<{ batch_id: string }> {
  return requestJson<{ batch_id: string }>("/api/batch-jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getBatch(batchId: string): Promise<JobState> {
  return requestJson<JobState>(`/api/batches/${batchId}`);
}

export function submitStageRun(stageName: string, payload: StageRunPayload): Promise<{ run_id: string }> {
  return requestJson<{ run_id: string }>(`/api/stages/${stageName}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getStageRun(runId: string): Promise<JobState> {
  return requestJson<JobState>(`/api/stage-runs/${runId}`);
}
