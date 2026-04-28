import { useState, useEffect } from 'react';
import { BASE_URL } from '../api/client';

export interface ProgressStep {
    step: number;
    step_name: string;
    status: 'running' | 'done' | 'failed';
    timestamp: string;
    data?: any;
}

export function useBuildProgress(buildId: string | undefined) {
    const [steps, setSteps] = useState<ProgressStep[]>([]);
    const [wsStatus, setWsStatus] = useState<"connecting" | "live" | "done" | "error">("connecting");

    useEffect(() => {
        if (!buildId) return;

        // Reset state on ID change
        setSteps([]);
        setWsStatus("connecting");

        // Use appropriate ws:// or wss:// depending on BASE_URL
        const wsProtocol = BASE_URL.startsWith('https') ? 'wss' : 'ws';
        const hostname = BASE_URL.replace(/^https?:\/\//, '');
        const wsUrl = `${wsProtocol}://${hostname}/ws/jobs/${buildId}`;

        const ws = new WebSocket(wsUrl);

        ws.onopen = () => setWsStatus("live");
        ws.onerror = (e) => {
            console.error("WebSocket error:", e);
            setWsStatus("error");
        };

        ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                if (msg.type === "history") {
                    setSteps(msg.steps);
                } else if (msg.type === "progress") {
                    setSteps(prev => {
                        // avoid duplicate latest step updates if backend sends progress multiple times
                        const newSteps = [...prev];
                        const existingIdx = newSteps.findIndex(s => s.step === msg.step);
                        if (existingIdx !== -1) {
                            newSteps[existingIdx] = msg;
                        } else {
                            newSteps.push(msg);
                        }
                        return newSteps.sort((a,b) => a.step - b.step);
                    });
                } else if (msg.type === "complete") {
                    setWsStatus("done");
                    ws.close();
                } else if (msg.type === "error") {
                    setWsStatus("error");
                }
            } catch (err) {
                console.error("WebSocket parse error", err);
            }
        };

        return () => {
            if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
                ws.close();
            }
        };
    }, [buildId]);

    return { steps, wsStatus };
}
