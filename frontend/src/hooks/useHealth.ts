import { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { HealthStatus } from '../api/client';

export function useHealth() {
    const [health, setHealth] = useState<HealthStatus | null>(null);

    useEffect(() => {
        const fetchHealth = async () => {
            try {
                const data = await api.getHealth();
                setHealth(data);
            } catch (err) {
                console.error("Failed to fetch health status", err);
            }
        };
        fetchHealth();
        const interval = setInterval(fetchHealth, 30000); // 30s
        return () => clearInterval(interval);
    }, []);

    return health;
}
