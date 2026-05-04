export const BASE_URL = (import.meta.env?.VITE_API_URL as string) ?? 'http://localhost:8000';

// ── Project types ──────────────────────────────────────────────────────────────

export interface Project {
    build_id:         string;
    prompt:           string;
    app_name?:        string;
    app_type?:        string;
    complexity?:      string;
    status:           string;
    debug_score?:     string;
    review_score?:    number;
    test_score?:      string;
    created_at:       string;
    completed_at?:    string;
    duration_seconds?: number;
}

export interface ProjectList {
    projects: Project[];
    total:    number;
    limit:    number;
    offset:   number;
}

export interface ProjectDetail extends Project {
    // Bug fix: the API (projects.py line 83) returns files as a plain
    // string[] — `project["files"] = [f["file_path"] for f in files]`
    // The old type `Array<{file_path, file_type}>` caused undefined errors
    // whenever any component did `f.file_path` on the items.
    files:      string[];
    file_count: number;
    output_path?: string;
    error?:     string;
}

// ── Build / job types ──────────────────────────────────────────────────────────

export interface BuildResponse {
    // POST /projects/ returns { build_id, status, ... }
    build_id: string;
    status:   string;
}

export interface RebuildResponse {
    // POST /projects/{id}/rebuild returns a DIFFERENT shape to BuildResponse.
    // The field is `new_build_id`, NOT `build_id`.
    // This was the root cause of the rebuild bug: res.build_id was always
    // undefined, navigating to /build/undefined.
    message:            string;
    original_build_id:  string;
    new_build_id:       string;   // ← the field that actually exists
    prompt:             string;
    status_url:         string;
}

export interface JobStatus {
    build_id:           string;
    status:             string;
    current_step:       number;
    total_steps:        number;
    step_name:          string;
    step_status:        string;
    elapsed_seconds?:   number;
    estimated_remaining_seconds?: number;
    duration_seconds?:  number;
    progress: {
        step:       number;
        step_name:  string;
        percent:    number;
        completed_steps: Array<{
            step:   number;
            name:   string;
            status: string;
            at:     string;
        }>;
        remaining_steps: string[];
    };
    // Result fields (populated when done)
    app_name?:     string;
    app_type?:     string;
    complexity?:   string;
    review_score?: number;
    debug_score?:  string;
    test_score?:   string;
    output_path?:  string;
}

export interface QueueStats {
    running:  number;
    queued:   number;
    workers:  {
        max:                number;
        active:             number;
        available:          number;
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

export interface PlatformStats {
    total_builds:           number;
    // Bug fix: the old interface was missing avg_duration_seconds which is
    // the top-level convenience field the fixed analytics.py now returns.
    // Components were falling back to duration_seconds.average which was
    // undefined → Math.round(undefined) → NaN displayed on screen.
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
    // Bug fix: the old type was `Record<string, number>` (a plain object).
    // The fixed analytics.py returns an array of {type, count} objects.
    top_app_types:          Array<{ type: string; count: number }>;
    average_review_score:   number | null;
    generated_at:           string;
}

export interface DailyStatsEntry {
    date:      string;
    total:     number;
    // Bug fix: the chart uses dataKey="success" but old type had no `success`
    // field — it only had `done`. The fixed analytics.py renames done→success.
    success:   number;
    failed:    number;
    cancelled: number;
}

export interface DailyStatsResponse {
    // Bug fix: the API returns { days, data: [...] }, NOT a bare array.
    // The old type `DailyStats[]` caused Statistics.tsx to try to map over
    // the wrapper object, getting undefined for all values.
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
        // Try to extract FastAPI's detail message for better error display
        let detail = `${res.status} ${res.statusText}`;
        try {
            const body = await res.json();
            if (body?.detail) detail = body.detail;
        } catch { /* ignore parse errors */ }
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

    // Bug fix: return type is now RebuildResponse (has new_build_id)
    // NOT BuildResponse (which has build_id).
    // The old typing caused ProjectDetail.tsx to read res.build_id → undefined
    // → navigated to /build/undefined → WebSocket /ws/jobs/undefined → stuck.
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

    // Bug fix: return type is DailyStatsResponse (wrapped), not DailyStats[].
    getDailyStats: (days = 30) =>
        fetchAPI<DailyStatsResponse>(`/stats/daily?days=${days}`),

    // ── Admin ──────────────────────────────────────────────────────────────────

    cleanup: (dry_run = true) =>
        fetchAPI<{ deleted: number; dry_run: boolean }>(
            '/projects/cleanup',
            { method: 'DELETE', body: JSON.stringify({ dry_run }) }
        ),

    resetKeys: () =>
        fetchAPI<{ message: string; keys_available: number; keys: Array<{ suffix: string; status: string }> }>('/admin/reset-keys', {
            method: 'POST',
        }),

    // ── Health ─────────────────────────────────────────────────────────────────

    getHealth: () =>
        fetchAPI<HealthStatus>('/health'),
};
