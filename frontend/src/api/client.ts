export const BASE_URL = (import.meta.env?.VITE_API_URL as string) ?? 'http://localhost:8000';

// ── Project types ──────────────────────────────────────────────────────────────

export interface Project {
    build_id:          string;
    prompt:            string;
    app_name?:         string;
    app_type?:         string;
    complexity?:       string;
    status:            string;
    debug_score?:      string;
    review_score?:     number;
    test_score?:       string;
    created_at:        string;
    completed_at?:     string;
    duration_seconds?: number;
    // Phase 17: token tracking
    prompt_tokens?:     number;
    completion_tokens?: number;
    total_tokens?:      number;
}

export interface ProjectList {
    projects: Project[];
    total:    number;
    limit:    number;
    offset:   number;
}

export interface ProjectDetail extends Project {
    files:        string[];
    file_count:   number;
    output_path?: string;
    error?:       string;
}

// ── Build / job types ──────────────────────────────────────────────────────────

export interface BuildResponse {
    build_id: string;
    status:   string;
}

export interface RebuildResponse {
    message:           string;
    original_build_id: string;
    new_build_id:      string;
    prompt:            string;
    status_url:        string;
}

export interface JobStatus {
    build_id:                     string;
    status:                       string;
    current_step:                 number;
    total_steps:                  number;
    step_name:                    string;
    step_status:                  string;
    elapsed_seconds?:             number;
    estimated_remaining_seconds?: number;
    duration_seconds?:            number;
    progress: {
        step:       number;
        step_name:  string;
        percent:    number;
        completed_steps: Array<{
            step:   number;
            name:   string;
            status: string;
            at:     string;
            // Phase 17: structured step data (elapsed_seconds, error, etc.)
            data?:  Record<string, unknown>;
        }>;
        remaining_steps: string[];
    };
    app_name?:     string;
    app_type?:     string;
    complexity?:   string;
    review_score?: number;
    debug_score?:  string;
    test_score?:   string;
    output_path?:  string;
}

export interface QueueStats {
    running: number;
    queued:  number;
    workers: {
        max:                 number;
        active:              number;
        available:           number;
        utilization_percent: number;
    };
}

export interface ActiveJobs {
    running: Array<{
        build_id:   string;
        app_name?:  string;
        status:     string;
        created_at: string;
    }>;
    queued: Array<{
        build_id:       string;
        queue_position: number;
        status:         string;
        created_at:     string;
    }>;
    total_active: number;
}

// ── Stats types ────────────────────────────────────────────────────────────────

// Phase 17: token usage block returned by /stats
export interface TokenUsageStats {
    total_prompt_tokens:     number;
    total_completion_tokens: number;
    total_tokens:            number;
    avg_tokens_per_build:    number | null;
}

export interface PlatformStats {
    total_builds:           number;
    avg_duration_seconds:   number | null;
    duration_seconds: {
        average: number | null;
        min:     number | null;
        max:     number | null;
    };
    success_rate_percent:   number;
    builds_today:           number;
    builds_this_week:       number;
    by_status:              Record<string, number>;
    top_app_types:          Array<{ type: string; count: number }>;
    average_review_score:   number | null;
    // Phase 17
    token_usage:            TokenUsageStats;
    generated_at:           string;
}

export interface DailyStatsEntry {
    date:          string;
    total:         number;
    success:       number;
    failed:        number;
    cancelled:     number;
    // Phase 17
    total_tokens:  number;
}

export interface DailyStatsResponse {
    days: number;
    data: DailyStatsEntry[];
}

export interface HealthStatus {
    status:      string;
    version:     string;
    timestamp:   string;
    worker_pool: {
        max:                 number;
        active:              number;
        available:           number;
        utilization_percent: number;
    };
    llm: {
        status:                string;
        provider:              string;
        groq_keys_total:       number;
        groq_keys_available:   number;
        groq_keys_exhausted:   number;
        keys: Array<{ suffix: string; status: string }>;
    };
    features: Record<string, boolean>;
}

// ── API client ─────────────────────────────────────────────────────────────────

async function fetchAPI<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const res = await fetch(`${BASE_URL}${endpoint}`, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...(options.headers ?? {}),
        },
    });

    if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try {
            const body = await res.json();
            if (body?.detail) detail = body.detail;
        } catch { /* ignore */ }
        throw new Error(`API Error: ${detail}`);
    }

    return res.json() as Promise<T>;
}

export const api = {

    // ── Projects ───────────────────────────────────────────────────────────────

    createProject: (prompt: string) =>
        fetchAPI<BuildResponse>('/projects/', {
            method: 'POST',
            body:   JSON.stringify({ prompt }),
        }),

    listProjects: (limit = 50, offset = 0, status?: string) => {
        const q = new URLSearchParams({
            limit:  limit.toString(),
            offset: offset.toString(),
        });
        if (status) q.append('status', status);
        return fetchAPI<ProjectList>(`/projects/?${q.toString()}`);
    },

    getProject: (id: string) =>
        fetchAPI<ProjectDetail>(`/projects/${id}`),

    deleteProject: (id: string) =>
        fetchAPI<{ message: string; build_id: string; files_deleted: boolean }>(
            `/projects/${id}`,
            { method: 'DELETE' }
        ),

    rebuildProject: (id: string) =>
        fetchAPI<RebuildResponse>(`/projects/${id}/rebuild`, { method: 'POST' }),

    downloadZip: (id: string) => {
        window.open(`${BASE_URL}/projects/${id}/download`, '_blank');
    },

    // ── Jobs ───────────────────────────────────────────────────────────────────

    getJobStatus: (id: string) =>
        fetchAPI<JobStatus>(`/jobs/${id}/status`),

    getQueue: () =>
        fetchAPI<QueueStats>('/jobs/queue'),

    cancelJob: (id: string) =>
        fetchAPI<{ message: string }>(`/jobs/${id}`, { method: 'DELETE' }),

    getActiveJobs: () =>
        fetchAPI<ActiveJobs>('/jobs/active'),

    // ── Stats ──────────────────────────────────────────────────────────────────

    getStats: () =>
        fetchAPI<PlatformStats>('/stats'),

    getDailyStats: (days = 30) =>
        fetchAPI<DailyStatsResponse>(`/stats/daily?days=${days}`),

    // ── Admin ──────────────────────────────────────────────────────────────────

    cleanup: (dry_run = true) =>
        fetchAPI<{ deleted: number; dry_run: boolean }>(
            '/projects/cleanup',
            { method: 'DELETE', body: JSON.stringify({ dry_run }) }
        ),

    resetKeys: () =>
        fetchAPI<{
            message:         string;
            keys_available:  number;
            keys: Array<{ suffix: string; status: string }>;
        }>('/admin/reset-keys', { method: 'POST' }),

    // ── Health ─────────────────────────────────────────────────────────────────

    getHealth: () =>
        fetchAPI<HealthStatus>('/health'),
};
