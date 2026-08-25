import type { ReactElement, ReactNode } from 'react';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

/**
 * Pages need a router and a query client. Each test gets a fresh client with
 * retries off and no background refetching — otherwise a deliberately-failing
 * request retries three times before the error state appears, and the test
 * either times out or passes for the wrong reason.
 */
export function renderPage(ui: ReactElement, { route = '/' } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false, gcTime: 0, staleTime: Infinity },
      mutations: { retry: false },
    },
  });

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  }

  return { queryClient, ...render(ui, { wrapper: Wrapper }) };
}

/** A project row shaped like the API's, overridable per test. */
export function project(over: Record<string, unknown> = {}) {
  return {
    build_id: 'fb3e4b24-5491-4925-bdb2-4a096df4735f',
    prompt: 'Build a task manager with drag and drop boards',
    app_name: 'TaskFlow',
    app_type: 'web_app',
    complexity: 'moderate',
    status: 'done',
    review_score: 8.4,
    debug_score: '9/10',
    test_score: '3/5',
    created_at: '2026-08-20T10:00:00.000Z',
    completed_at: '2026-08-20T10:06:00.000Z',
    duration_seconds: 362,
    ...over,
  };
}

/** A `/stats` body shaped like the API's. */
export function stats(over: Record<string, unknown> = {}) {
  return {
    total_builds: 42,
    avg_duration_seconds: 361,
    duration_seconds: { average: 361, min: 120, max: 900 },
    success_rate_percent: 76.2,
    builds_today: 3,
    builds_this_week: 11,
    by_status: { done: 32, failed: 6, cancelled: 2, running: 1, queued: 1 },
    top_app_types: [{ type: 'web_app', count: 18 }, { type: 'rest_api', count: 12 }],
    average_review_score: 7.8,
    token_usage: {
      total_prompt_tokens: 1_200_000,
      total_completion_tokens: 400_000,
      total_tokens: 1_600_000,
      avg_tokens_per_build: 38_095,
    },
    generated_at: '2026-08-25T10:00:00.000Z',
    ...over,
  };
}
