import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { HealthStatus } from '../api/client';

/**
 * Returns { health, refetch }.
 *
 * Was a hand-rolled useState + useEffect + setInterval, which is exactly what
 * every other data hook in the app already gets from react-query — and which
 * tripped the `set-state-in-effect` rule by kicking off its first fetch from
 * the effect body. Same contract, none of the machinery.
 *
 * `refetch` is stable, so it is safe to pass straight to an event handler.
 */
export function useHealth() {
  const { data, refetch } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.getHealth(),
    refetchInterval: 30_000,
    // The status pill is ambient: a failed poll should leave the last known
    // reading on screen rather than blanking it out.
    retry: 1,
  });

  return { health: (data ?? null) as HealthStatus | null, refetch };
}
