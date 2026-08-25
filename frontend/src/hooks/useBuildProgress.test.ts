import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useBuildProgress } from './useBuildProgress';

/**
 * A WebSocket stand-in we can drive from the test. The real one never connects
 * under jsdom, and the merge logic — which is where every bug in this hook
 * lived — is only reachable through message events.
 */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;
  static CONNECTING = 0;

  url: string;
  readyState = FakeWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((e: unknown) => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.closed = true;
    this.readyState = 3;
  }

  /** Drive a server frame into the hook. */
  emit(payload: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

const VALID_ID = 'fb3e4b24-5491-4925-bdb2-4a096df4735f';

/** Minimal `/jobs/{id}/status` body. */
function jobStatus(over: Record<string, unknown> = {}) {
  return {
    build_id: VALID_ID,
    status: 'running',
    total_steps: 9,
    progress: { percent: 22, completed_steps: [], remaining_steps: [] },
    ...over,
  };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
  fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => jobStatus() });
  vi.stubGlobal('fetch', fetchMock);
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'debug').mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const socket = () => FakeWebSocket.instances[0];

describe('useBuildProgress', () => {
  describe('the "undefined" build id guard', () => {
    /**
     * Navigating to /build/undefined used to open a socket the server closes
     * immediately, and the page showed "Build Failed" before any work started.
     */
    it.each(['undefined', 'null', 'abc'])('opens no socket for %s', (id) => {
      const { result } = renderHook(() => useBuildProgress(id));
      expect(FakeWebSocket.instances).toHaveLength(0);
      expect(result.current.wsStatus).toBe('error');
    });

    it('opens no socket when the id is missing entirely', () => {
      renderHook(() => useBuildProgress(undefined));
      expect(FakeWebSocket.instances).toHaveLength(0);
    });

    it('does connect for a real id', () => {
      renderHook(() => useBuildProgress(VALID_ID));
      expect(FakeWebSocket.instances).toHaveLength(1);
      expect(socket().url).toContain(`/ws/jobs/${VALID_ID}`);
    });
  });

  describe('step merging', () => {
    it('records a streamed progress event', () => {
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      act(() => {
        socket().emit({
          type: 'progress', step: 1, step_name: 'intent_analyzer',
          status: 'running', timestamp: '2026-08-25T10:00:00.000Z',
        });
      });
      expect(result.current.steps).toHaveLength(1);
      expect(result.current.steps[0].step_name).toBe('intent_analyzer');
    });

    /**
     * Slots 5, 8 and 9 run two agents each. Keying on the step number alone
     * meant the second agent overwrote the first.
     */
    it('keeps both agents that share one slot', () => {
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      act(() => {
        socket().emit({ type: 'progress', step: 5, step_name: 'frontend_generator', status: 'done', timestamp: '2026-08-25T10:00:00.000Z' });
        socket().emit({ type: 'progress', step: 5, step_name: 'frontend_debugger', status: 'running', timestamp: '2026-08-25T10:01:00.000Z' });
      });
      expect(result.current.steps).toHaveLength(2);
      expect(result.current.steps.map(s => s.step_name))
        .toEqual(expect.arrayContaining(['frontend_generator', 'frontend_debugger']));
    });

    it('updates in place when the same agent reports twice', () => {
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      act(() => {
        socket().emit({ type: 'progress', step: 1, step_name: 'intent_analyzer', status: 'running', timestamp: '2026-08-25T10:00:00.000Z' });
        socket().emit({ type: 'progress', step: 1, step_name: 'intent_analyzer', status: 'done', timestamp: '2026-08-25T10:00:30.000Z' });
      });
      expect(result.current.steps).toHaveLength(1);
      expect(result.current.steps[0].status).toBe('done');
    });

    it('parses a data payload that arrives as a JSON string', () => {
      // The socket sends an object; `/jobs/{id}/status` sends a JSON *string*.
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      act(() => {
        socket().emit({
          type: 'progress', step: 7, step_name: 'reviewer', status: 'done',
          timestamp: '2026-08-25T10:00:00.000Z',
          data: JSON.stringify({ avg_score: 8.4 }),
        });
      });
      expect(result.current.steps[0].data).toEqual({ avg_score: 8.4 });
    });

    it('survives a malformed frame without losing prior state', () => {
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      act(() => {
        socket().emit({ type: 'progress', step: 1, step_name: 'intent_analyzer', status: 'done', timestamp: '2026-08-25T10:00:00.000Z' });
        socket().onmessage?.({ data: 'not json at all' });
      });
      expect(result.current.steps).toHaveLength(1);
    });
  });

  describe('the terminal slot -1 event', () => {
    it('surfaces a pipeline failure as terminalStep', () => {
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      act(() => {
        socket().emit({
          type: 'progress', step: -1, step_name: 'error', status: 'failed',
          timestamp: '2026-08-25T10:05:00.000Z',
          data: { error: 'boom' },
        });
      });
      expect(result.current.terminalStep).not.toBeNull();
      expect(result.current.terminalStep!.data).toEqual({ error: 'boom' });
    });

    it('keeps slot -1 out of the numbered step list', () => {
      // Otherwise it would be drawn as a pipeline agent, which it is not.
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      act(() => {
        socket().emit({ type: 'progress', step: 1, step_name: 'intent_analyzer', status: 'done', timestamp: '2026-08-25T10:00:00.000Z' });
        socket().emit({ type: 'progress', step: -1, step_name: 'error', status: 'failed', timestamp: '2026-08-25T10:05:00.000Z', data: { error: 'boom' } });
      });
      expect(result.current.steps).toHaveLength(1);
      expect(result.current.steps[0].step).toBe(1);
    });

    it('does not treat the slot -1 completion event as a failure', () => {
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      act(() => {
        socket().emit({
          type: 'progress', step: -1, step_name: 'complete', status: 'done',
          timestamp: '2026-08-25T10:05:00.000Z', data: { reason: 'all good' },
        });
      });
      expect(result.current.terminalStep).toBeNull();
    });
  });

  describe('build completion', () => {
    it('marks the build done and closes the socket on complete', () => {
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      act(() => {
        socket().emit({ type: 'complete', status: 'done' });
      });
      expect(result.current.buildDone).toBe(true);
      expect(result.current.buildStatus).toBe('done');
      expect(socket().closed).toBe(true);
    });

    it('keeps wsStatus done after the server closes cleanly', () => {
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      act(() => {
        socket().emit({ type: 'complete', status: 'done' });
        socket().onclose?.({ code: 1000, wasClean: true });
      });
      expect(result.current.wsStatus).toBe('done');
    });

    it('records the status from a status_change frame', () => {
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      act(() => {
        socket().emit({ type: 'status_change', status: 'running' });
      });
      expect(result.current.buildStatus).toBe('running');
    });

    it('ignores keepalive pings', () => {
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      act(() => { socket().emit({ type: 'ping' }); });
      expect(result.current.steps).toHaveLength(0);
      expect(result.current.wsStatus).not.toBe('error');
    });
  });

  describe('the REST poll', () => {
    it('surfaces the job metadata the socket does not carry', async () => {
      fetchMock.mockResolvedValue({
        ok: true,
        json: async () => jobStatus({
          elapsed_seconds: 142,
          estimated_remaining_seconds: 260,
          queue_position: 3,
          total_steps: 9,
        }),
      });
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      await waitFor(() => expect(result.current.meta.elapsedSeconds).toBe(142));
      expect(result.current.meta.remainingSeconds).toBe(260);
      expect(result.current.meta.queuePosition).toBe(3);
      expect(result.current.meta.totalSteps).toBe(9);
    });

    /**
     * The polled payload is poorer than the streamed one — it can carry no
     * `data` at all. It must never erase a payload already held, or every
     * elapsed time and error message vanished after a reconnect.
     */
    it('does not let a polled step erase a streamed payload', async () => {
      fetchMock.mockResolvedValue({
        ok: true,
        json: async () => jobStatus({
          progress: {
            percent: 11,
            remaining_steps: [],
            completed_steps: [
              { step: 7, name: 'reviewer', status: 'done', at: '2026-08-25T10:00:00.000Z', data: null },
            ],
          },
        }),
      });

      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      act(() => {
        socket().emit({
          type: 'progress', step: 7, step_name: 'reviewer', status: 'done',
          timestamp: '2026-08-25T10:00:00.000Z', data: { avg_score: 8.4 },
        });
      });

      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      await waitFor(() => {
        expect(result.current.steps.find(s => s.step === 7)?.data).toEqual({ avg_score: 8.4 });
      });
    });

    it('parses the JSON-string data the REST endpoint returns', async () => {
      fetchMock.mockResolvedValue({
        ok: true,
        json: async () => jobStatus({
          progress: {
            percent: 11, remaining_steps: [],
            completed_steps: [
              { step: 7, name: 'reviewer', status: 'done', at: '2026-08-25T10:00:00.000Z', data: '{"avg_score":9.1}' },
            ],
          },
        }),
      });
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      await waitFor(() => {
        expect(result.current.steps.find(s => s.step === 7)?.data).toEqual({ avg_score: 9.1 });
      });
    });

    it.each(['done', 'done_with_context', 'failed', 'cancelled'])(
      'promotes %s to a finished build',
      async (status) => {
        // Phase 21: done_with_context is terminal too. Without it the page
        // polled forever on a build that had already finished.
        fetchMock.mockResolvedValue({ ok: true, json: async () => jobStatus({ status }) });
        const { result } = renderHook(() => useBuildProgress(VALID_ID));
        await waitFor(() => expect(result.current.buildDone).toBe(true));
      }
    );

    it('does not mark a running build as finished', async () => {
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      expect(result.current.buildDone).toBe(false);
    });

    it('keeps going when a poll request fails', async () => {
      fetchMock.mockRejectedValue(new Error('network down'));
      const { result } = renderHook(() => useBuildProgress(VALID_ID));
      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      expect(result.current.steps).toEqual([]);
      expect(result.current.buildDone).toBe(false);
    });
  });

  describe('switching builds', () => {
    it('clears the previous build state when the id changes', () => {
      const { result, rerender } = renderHook(
        ({ id }) => useBuildProgress(id),
        { initialProps: { id: VALID_ID } }
      );
      act(() => {
        socket().emit({ type: 'progress', step: 1, step_name: 'intent_analyzer', status: 'done', timestamp: '2026-08-25T10:00:00.000Z' });
      });
      expect(result.current.steps).toHaveLength(1);

      rerender({ id: 'd715e3f9-ac30-4d62-947c-97976c75d87e' });

      // No leakage: the new build must not inherit the old one's spine.
      expect(result.current.steps).toEqual([]);
      expect(result.current.buildDone).toBe(false);
      expect(result.current.buildStatus).toBe('');
    });
  });
});
