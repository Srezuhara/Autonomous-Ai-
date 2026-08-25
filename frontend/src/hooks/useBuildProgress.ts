import { useState, useEffect, useMemo } from 'react';
import { BASE_URL, wsUrl, isTerminal } from '../api/client';

/**
 * A step status as the backend actually emits it.
 *
 * `done_with_context` was missing: the pipeline uses it for a step that
 * finished in a degraded state (quota paused, partial output), and because the
 * union did not include it the row rendered as "pending" — a step that had run
 * looked like one that had not started.
 */
export type StepStatus = 'running' | 'done' | 'failed' | 'done_with_context';

export interface ProgressStep {
    step:      number;
    step_name: string;
    status:    StepStatus;
    timestamp: string;
    data?:     Record<string, unknown>;
}

export type WsStatus = 'connecting' | 'live' | 'done' | 'error';

/**
 * The fields `/jobs/{id}/status` returns that nothing used to read. All of them
 * were being fetched on every poll and thrown away.
 */
export interface JobMeta {
    totalSteps?:         number;
    percent?:            number;
    elapsedSeconds?:     number;
    remainingSeconds?:   number;
    remainingSteps?:     string[];
    queuePosition?:      number;
    completionReason?:   string | null;
}

/** The step slot the runner uses for its terminal event — see mergeStep. */
export const TERMINAL_SLOT = -1;

// ── REST polling fallback ─────────────────────────────────────────────────────

async function fetchJobStatus(buildId: string) {
    const res = await fetch(`${BASE_URL}/jobs/${buildId}/status`);
    if (!res.ok) return null;
    return res.json();
}

/**
 * `/jobs/{id}/status` returns each step's `data` as a raw JSON *string*, while
 * the WebSocket sends it as an object. Both used to be dropped entirely on the
 * polling path, so after a reconnect every elapsed time and error payload
 * vanished from the page.
 */
function parseStepData(raw: unknown): Record<string, unknown> | undefined {
    if (raw == null) return undefined;
    if (typeof raw === 'object') return raw as Record<string, unknown>;
    if (typeof raw !== 'string') return undefined;
    try {
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : undefined;
    } catch {
        return undefined;
    }
}

function isEmpty(data: Record<string, unknown> | undefined): boolean {
    return !data || Object.keys(data).length === 0;
}

export function useBuildProgress(buildId: string | undefined) {
    const [steps,       setSteps]       = useState<ProgressStep[]>([]);
    const [wsStatus,    setWsStatus]    = useState<WsStatus>('connecting');
    const [buildDone,   setBuildDone]   = useState(false);
    const [buildStatus, setBuildStatus] = useState<string>('');
    const [meta,        setMeta]        = useState<JobMeta>({});

    /**
     * Guard against literally "undefined" arriving as a string. This was the
     * rebuild bug: navigating to /build/undefined opened a socket the server
     * closes immediately, and the page showed "Build Failed" before any work
     * had started.
     *
     * Derived rather than pushed into state through an effect — the old
     * version called setWsStatus in the effect body, which is a cascading
     * render and, for a value that is a pure function of the id, unnecessary.
     */
    const invalidId = !buildId
        || buildId === 'undefined'
        || buildId === 'null'
        || buildId.length < 4;

    /**
     * Reset when the id changes.
     *
     * Done during render — React's sanctioned "adjust state when a prop
     * changes" pattern — rather than from the socket effect's body. The effect
     * version called four setters during commit, which is a cascading render:
     * the page painted one build's steps under the next build's id before the
     * reset landed.
     */
    const [prevBuildId, setPrevBuildId] = useState(buildId);
    if (buildId !== prevBuildId) {
        setPrevBuildId(buildId);
        setSteps([]);
        setWsStatus('connecting');
        setBuildDone(false);
        setBuildStatus('');
        setMeta({});
    }

    // ── Merge a single step into state ────────────────────────────────────────
    /**
     * Keyed on step number *and* name, not number alone.
     *
     * Slots 5, 8 and 9 each carry two agents (frontend_generator +
     * frontend_debugger, tester + remediation, documenter + session_context).
     * Deduping on the number alone meant the second agent overwrote the first,
     * so the wrong name showed and React saw duplicate keys.
     *
     * The runner's terminal events land on slot -1 with the names "error" and
     * "complete"; they are kept, not discarded, and rendered as a terminal row.
     */
    const mergeStep = (msg: ProgressStep) => {
        setSteps(prev => {
            const key = (s: ProgressStep) => `${s.step}::${s.step_name}`;
            const next = [...prev];
            const idx = next.findIndex(s => key(s) === key(msg));

            if (idx === -1) {
                next.push(msg);
            } else {
                // A polled step is poorer than a streamed one: it may carry no
                // data at all. Never let it erase a payload we already have.
                const existing = next[idx];
                next[idx] = {
                    ...msg,
                    data: isEmpty(msg.data) ? existing.data : msg.data,
                };
            }

            // Terminal events sort last regardless of their -1 slot number.
            return next.sort((a, b) => {
                const av = a.step < 0 ? Infinity : a.step;
                const bv = b.step < 0 ? Infinity : b.step;
                return av - bv;
            });
        });
    };

    // ── WebSocket connection ───────────────────────────────────────────────────
    useEffect(() => {
        if (!buildId || invalidId) return;

        const ws = new WebSocket(wsUrl(`/ws/jobs/${buildId}`));

        ws.onopen = () => setWsStatus('live');

        ws.onerror = () => {
            // Don't surface "WS Error" — the REST poll below keeps the UI fed.
            console.warn('[WS] Error — REST polling will take over');
            setWsStatus('error');
        };

        ws.onmessage = (e: MessageEvent) => {
            let msg: Record<string, unknown>;
            try { msg = JSON.parse(e.data as string); }
            catch { return; }

            switch (msg.type as string) {

                // Sent immediately on connect — the current build status, and
                // the trigger for the history burst that follows.
                case 'status_change':
                    setBuildStatus(msg.status as string ?? '');
                    break;

                case 'progress':
                    mergeStep({
                        step:      msg.step      as number,
                        step_name: msg.step_name as string,
                        status:    msg.status    as StepStatus,
                        timestamp: msg.timestamp as string,
                        data:      parseStepData(msg.data),
                    });
                    break;

                // Build finished — the server closes the socket after this.
                case 'complete':
                    setBuildStatus(msg.status as string ?? '');
                    setBuildDone(true);
                    setWsStatus('done');
                    ws.close();
                    break;

                case 'ping':
                    break;

                // A server-side notice (e.g. "Build timeout" after 120s of
                // silence). NOT the same thing as the build failing.
                case 'error':
                    console.warn('[WS] Server error message:', msg.message);
                    setWsStatus('error');
                    break;

                default:
                    console.debug('[WS] Unknown message type:', msg.type, msg);
            }
        };

        ws.onclose = () => {
            // A clean close after 'complete' should stay 'done'.
            setWsStatus(prev => prev === 'done' ? 'done' : 'error');
        };

        return () => {
            if (ws.readyState === WebSocket.OPEN ||
                ws.readyState === WebSocket.CONNECTING) {
                ws.close();
            }
        };
    }, [buildId, invalidId]);

    // ── REST poll ─────────────────────────────────────────────────────────────
    /**
     * Runs alongside the socket rather than only after it fails.
     *
     * The socket carries steps; it carries none of the job metadata — elapsed
     * time, ETA, queue position, the authoritative step count. Those come from
     * here. Step merging is safe to do on both paths because `mergeStep`
     * refuses to downgrade a payload it already holds.
     */
    useEffect(() => {
        if (!buildId || invalidId) return;
        if (buildDone && wsStatus === 'done') return;

        let cancelled = false;

        const poll = async () => {
            try {
                const data = await fetchJobStatus(buildId);
                if (cancelled || !data) return;

                const status: string = data.status ?? '';
                setBuildStatus(status);

                setMeta({
                    totalSteps:       data.total_steps,
                    percent:          data.progress?.percent,
                    elapsedSeconds:   data.elapsed_seconds,
                    remainingSeconds: data.estimated_remaining_seconds,
                    remainingSteps:   data.progress?.remaining_steps,
                    queuePosition:    data.queue_position,
                    completionReason: data.completion_reason,
                });

                const completed: Array<{
                    step: number; name: string; status: string; at: string; data?: unknown;
                }> = data.progress?.completed_steps ?? [];

                completed.forEach(s => mergeStep({
                    step:      s.step,
                    step_name: s.name,
                    status:    s.status as StepStatus,
                    timestamp: s.at,
                    data:      parseStepData(s.data),
                }));

                // Phase 21: done_with_context is terminal too — without it the
                // page polls forever on a build that already finished.
                if (isTerminal(status)) {
                    setBuildDone(true);
                    setWsStatus(prev => prev === 'live' ? prev : 'done');
                }
            } catch (err) {
                console.warn('[REST poll] request failed:', err);
            }
        };

        poll();
        const interval = setInterval(poll, 5000);

        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, [buildId, invalidId, wsStatus, buildDone]);

    /**
     * The runner emits its terminal event on slot -1: `error`/`failed` when the
     * pipeline raised, `complete`/<final status> when it finished. Neither was
     * ever rendered — `StepTracker` only drew slots 1..9 — so a pipeline
     * failure showed as nine pending rows and no explanation anywhere.
     */
    const terminalStep = useMemo(
        () => steps.find(s => s.step === TERMINAL_SLOT && s.status === 'failed') ?? null,
        [steps],
    );

    const pipelineSteps = useMemo(
        () => steps.filter(s => s.step > 0),
        [steps],
    );

    return {
        steps: pipelineSteps,
        terminalStep,
        wsStatus: invalidId ? 'error' as const : wsStatus,
        buildDone,
        buildStatus,
        meta,
    };
}
