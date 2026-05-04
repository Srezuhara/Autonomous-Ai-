import { useState, useEffect, useRef } from 'react';
import { BASE_URL } from '../api/client';

export interface ProgressStep {
    step:      number;
    step_name: string;
    status:    'running' | 'done' | 'failed';
    timestamp: string;
    data?:     unknown;
}

export type WsStatus = 'connecting' | 'live' | 'done' | 'error';

// ── REST polling fallback ─────────────────────────────────────────────────────
async function fetchJobStatus(buildId: string) {
    const res = await fetch(`${BASE_URL}/jobs/${buildId}/status`);
    if (!res.ok) return null;
    return res.json();
}

export function useBuildProgress(buildId: string | undefined) {
    const [steps,       setSteps]       = useState<ProgressStep[]>([]);
    const [wsStatus,    setWsStatus]    = useState<WsStatus>('connecting');
    const [buildDone,   setBuildDone]   = useState(false);
    const [buildStatus, setBuildStatus] = useState<string>('');

    const wsRef = useRef<WebSocket | null>(null);

    // ── Merge a single step into state ────────────────────────────────────────
    const mergeStep = (msg: ProgressStep) => {
        setSteps(prev => {
            const next = [...prev];
            const idx  = next.findIndex(s => s.step === msg.step);
            if (idx !== -1) {
                next[idx] = msg;
            } else {
                next.push(msg);
            }
            return next.sort((a, b) => a.step - b.step);
        });
    };

    // ── WebSocket connection ───────────────────────────────────────────────────
    useEffect(() => {
        if (!buildId) return;

        // Guard against literally "undefined" being passed as a string
        // This was the rebuild bug: navigation to /build/undefined caused
        // the WS to connect to /ws/jobs/undefined which the server closes
        // immediately, showing "Build Failed" before any work started.
        if (buildId === 'undefined' || buildId === 'null' || buildId.length < 4) {
            console.error('[WS] Invalid buildId received:', buildId);
            setWsStatus('error');
            return;
        }

        // Reset for new build
        setSteps([]);
        setWsStatus('connecting');
        setBuildDone(false);
        setBuildStatus('');

        const proto = BASE_URL.startsWith('https') ? 'wss' : 'ws';
        const host  = BASE_URL.replace(/^https?:\/\//, '');
        const url   = `${proto}://${host}/ws/jobs/${buildId}`;

        console.log('[WS] Connecting:', url);
        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
            console.log('[WS] Connected');
            setWsStatus('live');
        };

        ws.onerror = () => {
            // Don't show "WS Error" to the user — the REST polling fallback
            // will silently keep the UI updated.
            console.warn('[WS] Error — REST polling will take over');
            setWsStatus('error');
        };

        ws.onmessage = (e: MessageEvent) => {
            let msg: Record<string, unknown>;
            try { msg = JSON.parse(e.data as string); }
            catch { return; }

            switch (msg.type as string) {

                // Sent immediately on connect — tells us the current build status
                // and triggers the history burst that follows.
                case 'status_change':
                    setBuildStatus(msg.status as string ?? '');
                    break;

                // Individual pipeline step update (running / done / failed)
                case 'progress':
                    mergeStep({
                        step:      msg.step      as number,
                        step_name: msg.step_name as string,
                        status:    msg.status    as 'running' | 'done' | 'failed',
                        timestamp: msg.timestamp as string,
                        data:      msg.data,
                    });
                    break;

                // Build finished — server closes the socket after this
                case 'complete':
                    setBuildStatus(msg.status as string ?? '');
                    setBuildDone(true);
                    setWsStatus('done');
                    ws.close();
                    break;

                // Server keepalive — ignore silently
                case 'ping':
                    break;

                // Server-side error message (e.g. "Build timeout" after 120s silence)
                // This is NOT the same as a build failure — just log it.
                case 'error':
                    console.warn('[WS] Server error message:', msg.message);
                    setWsStatus('error');
                    break;

                default:
                    console.debug('[WS] Unknown message type:', msg.type, msg);
            }
        };

        ws.onclose = (e: CloseEvent) => {
            console.log('[WS] Closed — code:', e.code, 'clean:', e.wasClean);
            // Only set error if we haven't already confirmed done.
            // A clean server close after 'complete' should stay as 'done'.
            setWsStatus(prev => prev === 'done' ? 'done' : 'error');
        };

        return () => {
            if (ws.readyState === WebSocket.OPEN ||
                ws.readyState === WebSocket.CONNECTING) {
                ws.close();
            }
            wsRef.current = null;
        };
    }, [buildId]);

    // ── REST polling fallback ─────────────────────────────────────────────────
    // Activates when WS errors out (e.g. build already finished before page
    // loaded, network blip, or the ws/jobs/undefined guard above triggered).
    // Also runs after WS 'done' to pull the final completed_steps list in case
    // any steps were missed during the stream.
    useEffect(() => {
        if (!buildId || buildId === 'undefined') return;
        // Only poll when WS is not live
        if (wsStatus !== 'error' && wsStatus !== 'done') return;
        // Don't keep polling once build is confirmed done
        if (buildDone && wsStatus === 'done') return;

        let cancelled = false;

        const poll = async () => {
            try {
                const data = await fetchJobStatus(buildId);
                if (cancelled || !data) return;

                const status: string = data.status ?? '';
                setBuildStatus(status);

                // Merge all completed steps from REST response
                const completed: Array<{ step: number; name: string; status: string; at: string }>
                    = data.progress?.completed_steps ?? [];
                completed.forEach(s => mergeStep({
                    step:      s.step,
                    step_name: s.name,
                    status:    s.status as 'running' | 'done' | 'failed',
                    timestamp: s.at,
                }));

                if (['done', 'failed', 'cancelled'].includes(status)) {
                    setBuildDone(true);
                    setWsStatus('done');
                }
            } catch (err) {
                console.warn('[REST poll] request failed:', err);
            }
        };

        poll(); // immediate first poll
        const interval = setInterval(poll, 5000);

        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, [buildId, wsStatus, buildDone]);

    return { steps, wsStatus, buildDone, buildStatus };
}
