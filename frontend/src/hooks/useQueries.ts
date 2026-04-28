import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

export function useBuilds(status?: string) {
    return useQuery({
        queryKey: ['projects', status],
        queryFn: () => api.listProjects(50, 0, status),
        refetchInterval: 10000, // Poll every 10s for updates
    });
}

export function useStats() {
    return useQuery({
        queryKey: ['stats'],
        queryFn: () => api.getStats(),
        refetchInterval: 30000,
    });
}

export function useDailyStats(days = 14) {
    return useQuery({
        queryKey: ['stats', 'daily', days],
        queryFn: () => api.getDailyStats(days),
    });
}

export function useProjectDetail(id: string | undefined) {
    return useQuery({
        queryKey: ['project', id],
        queryFn: () => id ? api.getProject(id) : Promise.reject("No ID"),
        enabled: !!id,
    });
}
