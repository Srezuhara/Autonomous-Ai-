export const BASE_URL = 'http://localhost:8000';

export interface ProjectList {
    projects: Project[];
    total: number;
}

export interface Project {
    build_id: string;
    prompt: string;
    app_name?: string;
    app_type?: string;
    complexity?: string;
    status: string;
    debug_score?: string;
    review_score?: number;
    test_score?: string;
    created_at: string;
    completed_at?: string;
    duration_seconds?: number;
}

export interface ProjectDetail extends Project {
    files: Array<{
        file_path: string;
        file_type?: string;
    }>;
}

export interface BuildResponse {
    build_id: string;
    status: string;
}

export interface JobStatus {
    build_id: string;
    status: string;
    elapsed_seconds: number;
    remaining_seconds?: number;
    percent?: number;
}

export interface QueueStats {
    workers_total: number;
    workers_busy: number;
    queued_jobs: number;
}

export interface ActiveJobs {
    running: any[];
    queued: any[];
}

export interface PlatformStats {
    total_builds: number;
    success_rate_percent: number;
    avg_duration_seconds: number;
    top_app_types: Record<string, number>;
}

export interface DailyStats {
    date: string;
    success: number;
    failed: number;
    total: number;
}

export interface HealthStatus {
    status: string;
    version: string;
    worker_pool: any;
    llm: any;
    features: any;
}

async function fetchAPI<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const res = await fetch(`${BASE_URL}${endpoint}`, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...(options.headers || {}),
        },
    });
    if (!res.ok) {
        throw new Error(`API Error: ${res.status} ${res.statusText}`);
    }
    return res.json();
}

export const api = {
    createProject: (prompt: string) => 
        fetchAPI<BuildResponse>('/projects/', { method: 'POST', body: JSON.stringify({ prompt }) }),
        
    listProjects: (limit: number = 20, offset: number = 0, status?: string) => {
        const query = new URLSearchParams({ limit: limit.toString(), offset: offset.toString() });
        if (status) query.append('status', status);
        return fetchAPI<ProjectList>(`/projects/?${query.toString()}`);
    },

    getProject: (id: string) => fetchAPI<ProjectDetail>(`/projects/${id}`),
    
    deleteProject: (id: string) => fetchAPI<{message: string}>(`/projects/${id}`, { method: 'DELETE' }),

    getJobStatus: (id: string) => fetchAPI<JobStatus>(`/jobs/${id}/status`),
    
    getQueue: () => fetchAPI<QueueStats>('/jobs/queue'),
    
    cancelJob: (id: string) => fetchAPI<{message: string}>(`/jobs/${id}`, { method: 'DELETE' }),
    
    getActiveJobs: () => fetchAPI<ActiveJobs>('/jobs/active'),
    
    downloadZip: (id: string) => {
        window.open(`${BASE_URL}/projects/${id}/download`, '_blank');
    },
    
    getStats: () => fetchAPI<PlatformStats>('/stats'),
    
    getDailyStats: (days: number = 30) => fetchAPI<DailyStats[]>(`/stats/daily?days=${days}`),
    
    rebuildProject: (id: string) => fetchAPI<BuildResponse>(`/projects/${id}/rebuild`, { method: 'POST' }),
    
    cleanup: (dry_run: boolean = false) => fetchAPI<{deleted: number}>(`/projects/cleanup`, { 
        method: 'DELETE', 
        body: JSON.stringify({ dry_run }) 
    }),
    
    getHealth: () => fetchAPI<HealthStatus>('/health'),
};
