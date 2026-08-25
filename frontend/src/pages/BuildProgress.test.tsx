import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import BuildProgress from './BuildProgress';
import { renderPage } from '../test/harness';
import type { JobMeta, ProgressStep } from '../hooks/useBuildProgress';

const BUILD_ID = 'd715e3f9-ac30-4d62-947c-97976c75d87e';

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useParams: () => ({ id: BUILD_ID }) };
});

/**
 * The hook has its own suite; here we drive the page directly from its return
 * value so every terminal state is reachable without staging a socket.
 */
const progress = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock('../hooks/useBuildProgress', () => ({
  useBuildProgress: () => progress.value,
}));

const projectDetail = vi.hoisted(() => ({ value: undefined as unknown }));
vi.mock('../hooks/useQueries', () => ({
  useProjectDetail: () => ({ data: projectDetail.value }),
}));

vi.mock('../hooks/useHealth', () => ({
  useHealth: () => ({ health: { llm: { provider: 'groq' } }, refetch: vi.fn() }),
}));

function state(over: {
  steps?: ProgressStep[];
  terminalStep?: ProgressStep | null;
  wsStatus?: string;
  buildDone?: boolean;
  buildStatus?: string;
  meta?: JobMeta;
} = {}) {
  progress.value = {
    steps: [],
    terminalStep: null,
    wsStatus: 'live',
    buildDone: false,
    buildStatus: 'running',
    meta: {},
    ...over,
  };
}

beforeEach(() => {
  projectDetail.value = undefined;
  state();
});

describe('BuildProgress', () => {
  describe('terminal states', () => {
    /**
     * A cancelled build used to fall through to the success branch and read
     * "Build complete — your files are ready to download", which was false in
     * every particular.
     */
    it('does not tell a cancelled build it completed', () => {
      state({ buildDone: true, buildStatus: 'cancelled' });
      renderPage(<BuildProgress />);

      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Build cancelled');
      expect(screen.queryByText(/Build complete/)).not.toBeInTheDocument();
      expect(screen.queryByText(/ready to download/)).not.toBeInTheDocument();
    });

    it('offers a cancelled build a fresh start, not a download', () => {
      state({ buildDone: true, buildStatus: 'cancelled' });
      renderPage(<BuildProgress />);

      expect(screen.getByText(/Cancelled before completion/)).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: /View result/ })).not.toBeInTheDocument();
      expect(screen.getByRole('link', { name: /Start a new build/ })).toBeInTheDocument();
    });

    it('reports a successful build', () => {
      state({ buildDone: true, buildStatus: 'done' });
      renderPage(<BuildProgress />);
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Build complete');
      expect(screen.getByRole('link', { name: /View result/ })).toBeInTheDocument();
    });

    it('sends a done_with_context build down the success path, not the failure one', () => {
      // Phase 21: it produced downloadable code plus a handoff document.
      state({ buildDone: true, buildStatus: 'done_with_context' });
      renderPage(<BuildProgress />);
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Finished with notes');
      expect(screen.getByRole('link', { name: /View result/ })).toBeInTheDocument();
    });

    it('reports a failure', () => {
      state({ buildDone: true, buildStatus: 'failed' });
      renderPage(<BuildProgress />);
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Build failed');
    });
  });

  describe('failure text', () => {
    /**
     * `project.error` was read in three places and the column does not exist,
     * so the fallback string was the only thing that ever appeared.
     */
    it('prefers the runner\'s slot -1 error payload', () => {
      state({
        buildDone: true,
        buildStatus: 'failed',
        terminalStep: {
          step: -1, step_name: 'error', status: 'failed',
          timestamp: '2026-08-25T10:05:00.000Z',
          data: { error: 'GroqRateLimitError: all keys exhausted' },
        },
      });
      const { container } = renderPage(<BuildProgress />);

      // Deliberately in both places: on the spine's terminal row, where the
      // eye already is, and in the "What went wrong" panel, which is the
      // thing a user scrolls back to find.
      const hits = screen.getAllByText('GroqRateLimitError: all keys exhausted');
      expect(hits).toHaveLength(2);
      expect(container.querySelector('.srow--terminal')).toHaveTextContent('GroqRateLimitError');
      expect(container.querySelector('.bp-note--error')).toHaveTextContent('GroqRateLimitError');
    });

    it('falls back to completion_reason, the column that does exist', () => {
      projectDetail.value = { status: 'failed', completion_reason: 'Timed out during step 6' };
      state({ buildDone: true, buildStatus: 'failed' });
      renderPage(<BuildProgress />);
      expect(screen.getByText('Timed out during step 6')).toBeInTheDocument();
    });

    it('says something useful when neither source has anything', () => {
      state({ buildDone: true, buildStatus: 'failed' });
      renderPage(<BuildProgress />);
      expect(screen.getByText(/Check the step log above/)).toBeInTheDocument();
    });
  });

  describe('job metadata', () => {
    // All of this was returned by /jobs/{id}/status and thrown away.
    it('shows elapsed time', () => {
      state({ meta: { elapsedSeconds: 142, totalSteps: 9 } });
      renderPage(<BuildProgress />);
      expect(screen.getByText('Elapsed')).toBeInTheDocument();
      expect(screen.getByText('2m 22s')).toBeInTheDocument();
    });

    it('shows an ETA while the build is running', () => {
      state({ meta: { elapsedSeconds: 60, remainingSeconds: 240, totalSteps: 9 } });
      renderPage(<BuildProgress />);
      expect(screen.getByText('Est. remaining')).toBeInTheDocument();
      expect(screen.getByText('~4m')).toBeInTheDocument();
    });

    it('drops the ETA once the build is over', () => {
      state({ buildDone: true, buildStatus: 'done', meta: { elapsedSeconds: 300, remainingSeconds: 240 } });
      renderPage(<BuildProgress />);
      expect(screen.queryByText('Est. remaining')).not.toBeInTheDocument();
    });

    it('shows queue position and says so in the subtitle', () => {
      state({ buildStatus: 'queued', meta: { queuePosition: 3, totalSteps: 9 } });
      renderPage(<BuildProgress />);
      expect(screen.getByText('Queue position')).toBeInTheDocument();
      expect(screen.getByText(/position 3/)).toBeInTheDocument();
    });

    it('drives the step count from the server, not a hardcoded 9', () => {
      state({ meta: { totalSteps: 5 } });
      renderPage(<BuildProgress />);
      expect(screen.getAllByRole('listitem')).toHaveLength(5);
      expect(screen.getByText(/of 5/)).toBeInTheDocument();
    });
  });

  it('renders the pipeline failure row when the runner reports one', () => {
    state({
      buildDone: true,
      buildStatus: 'failed',
      terminalStep: {
        step: -1, step_name: 'error', status: 'failed',
        timestamp: '2026-08-25T10:05:00.000Z', data: { error: 'boom' },
      },
      meta: { totalSteps: 9 },
    });
    renderPage(<BuildProgress />);
    // Nine agent slots plus the terminal row.
    expect(screen.getAllByRole('listitem')).toHaveLength(10);
    expect(screen.getByText('Pipeline stopped')).toBeInTheDocument();
  });

  it('derives the rotation copy from the health provider instead of asserting Groq', () => {
    state();
    renderPage(<BuildProgress />);
    expect(screen.getByText(/groq keys rotate automatically/i)).toBeInTheDocument();
  });

  it('offers cancel only while the build is still running', () => {
    state();
    const { unmount } = renderPage(<BuildProgress />);
    expect(screen.getByRole('button', { name: /Cancel build/ })).toBeInTheDocument();
    unmount();

    state({ buildDone: true, buildStatus: 'done' });
    renderPage(<BuildProgress />);
    expect(screen.queryByRole('button', { name: /Cancel build/ })).not.toBeInTheDocument();
  });

  it('explains the polling fallback without alarming the user', () => {
    state({ wsStatus: 'error' });
    renderPage(<BuildProgress />);
    expect(screen.getByText(/Live stream unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/The build itself is\s+unaffected/)).toBeInTheDocument();
  });
});
