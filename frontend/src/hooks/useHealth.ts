import { useState, useEffect, useCallback } from 'react';
import { api } from '../api/client';
import type { HealthStatus } from '../api/client';

/**
 * Returns { health, refetch }.
 * `refetch` is stable — safe to pass to event handlers without re-renders.
 */
export function useHealth() {
  const [health, setHealth] = useState<HealthStatus | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      const data = await api.getHealth();
      setHealth(data);
    } catch (err) {
      console.error('Failed to fetch health status', err);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 30_000); // 30s polling
    return () => clearInterval(interval);
  }, [fetchHealth]);

  return { health, refetch: fetchHealth };
}
