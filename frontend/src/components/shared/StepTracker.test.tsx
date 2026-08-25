import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { StepTracker } from './StepTracker';
import type { ProgressStep } from '../../hooks/useBuildProgress';

function step(partial: Partial<ProgressStep> & Pick<ProgressStep, 'step' | 'step_name' | 'status'>): ProgressStep {
  return { timestamp: '2026-08-25T10:00:00.000Z', ...partial };
}

describe('StepTracker', () => {
  it('renders every slot, including ones with no event yet', () => {
    render(<StepTracker steps={[]} totalSteps={9} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(9);
  });

  it('drives the slot count from totalSteps rather than a hardcoded 9', () => {
    render(<StepTracker steps={[]} totalSteps={5} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(5);
    expect(screen.getByText(/of 5/)).toBeInTheDocument();
  });

  describe('step statuses', () => {
    it.each([
      ['running', 'running'],
      ['failed', 'failed'],
      ['done_with_context', 'partial'],
    ])('renders a %s step with its own tag', (status, tag) => {
      render(
        <StepTracker
          steps={[step({ step: 4, step_name: 'backend_developer', status: status as ProgressStep['status'] })]}
          totalSteps={9}
        />
      );
      expect(screen.getByText(tag)).toBeInTheDocument();
    });

    it('counts done_with_context toward completion, not against it', () => {
      // The step ran and produced something. Excluding it from the count made
      // a degraded-but-finished build look stalled.
      render(
        <StepTracker
          steps={[
            step({ step: 1, step_name: 'intent_analyzer', status: 'done' }),
            step({ step: 2, step_name: 'planner', status: 'done_with_context' }),
          ]}
          totalSteps={9}
        />
      );
      expect(screen.getByText('2')).toBeInTheDocument();
    });

    it('leaves a slot with no event as pending', () => {
      const { container } = render(<StepTracker steps={[]} totalSteps={9} />);
      expect(container.querySelectorAll('.srow--pending')).toHaveLength(9);
    });
  });

  describe('colliding slots', () => {
    /**
     * Slots 5, 8 and 9 each run two agents. The old hook deduped on the step
     * number alone, so the second agent silently overwrote the first and React
     * saw duplicate keys. The tracker now keeps the most recent event per slot.
     */
    it('shows the most recent agent for a slot that runs two', () => {
      render(
        <StepTracker
          steps={[
            step({ step: 5, step_name: 'frontend_generator', status: 'done', timestamp: '2026-08-25T10:00:00.000Z' }),
            step({ step: 5, step_name: 'frontend_debugger', status: 'running', timestamp: '2026-08-25T10:01:00.000Z' }),
          ]}
          totalSteps={9}
        />
      );
      expect(screen.getByText('Frontend Debugger')).toBeInTheDocument();
      expect(screen.queryByText('Frontend Generator')).not.toBeInTheDocument();
    });

    it('does not render a slot twice when two agents report on it', () => {
      render(
        <StepTracker
          steps={[
            step({ step: 8, step_name: 'tester', status: 'done' }),
            step({ step: 8, step_name: 'remediation', status: 'running' }),
          ]}
          totalSteps={9}
        />
      );
      expect(screen.getAllByRole('listitem')).toHaveLength(9);
    });

    it('is not confused by out-of-order arrival', () => {
      // Polling can deliver history after the socket has already streamed the
      // newer event. Recency is decided by timestamp, not array position.
      render(
        <StepTracker
          steps={[
            step({ step: 5, step_name: 'frontend_debugger', status: 'running', timestamp: '2026-08-25T10:01:00.000Z' }),
            step({ step: 5, step_name: 'frontend_generator', status: 'done', timestamp: '2026-08-25T10:00:00.000Z' }),
          ]}
          totalSteps={9}
        />
      );
      expect(screen.getByText('Frontend Debugger')).toBeInTheDocument();
    });
  });

  describe('the terminal failure row', () => {
    /**
     * The runner emits its pipeline-level failure on slot -1, outside the 1..N
     * range the list draws. It used to be dropped entirely, so a crashed
     * pipeline showed nine pending rows and no explanation anywhere on screen.
     */
    it('renders the slot -1 failure as an extra row', () => {
      render(
        <StepTracker
          steps={[]}
          totalSteps={9}
          terminalStep={step({
            step: -1,
            step_name: 'error',
            status: 'failed',
            data: { error: 'GroqRateLimitError: all keys exhausted' },
          })}
        />
      );
      expect(screen.getAllByRole('listitem')).toHaveLength(10);
      expect(screen.getByText('Pipeline stopped')).toBeInTheDocument();
    });

    it('shows the actual error text from the runner payload', () => {
      render(
        <StepTracker
          steps={[]}
          totalSteps={9}
          terminalStep={step({
            step: -1,
            step_name: 'error',
            status: 'failed',
            data: { error: 'GroqRateLimitError: all keys exhausted' },
          })}
        />
      );
      expect(screen.getByText(/GroqRateLimitError: all keys exhausted/)).toBeInTheDocument();
    });

    it('adds no extra row when the pipeline did not fail', () => {
      render(<StepTracker steps={[]} totalSteps={9} terminalStep={null} />);
      expect(screen.getAllByRole('listitem')).toHaveLength(9);
      expect(screen.queryByText('Pipeline stopped')).not.toBeInTheDocument();
    });
  });

  describe('step names', () => {
    it('prefers the name the server emitted over the fallback map', () => {
      render(
        <StepTracker
          steps={[step({ step: 9, step_name: 'session_context', status: 'running' })]}
          totalSteps={9}
        />
      );
      expect(screen.getByText('Session Context')).toBeInTheDocument();
    });

    it('names slot 9 Documenter, not the non-existent Packager', () => {
      render(<StepTracker steps={[]} totalSteps={9} />);
      expect(screen.getByText('Documenter')).toBeInTheDocument();
      expect(screen.queryByText('Packager')).not.toBeInTheDocument();
    });
  });

  describe('step detail', () => {
    /**
     * The old row rendered `data.message`, a field the pipeline has never
     * emitted — dead markup on every row. These are the shapes
     * `_build_step_data` actually produces.
     */
    it('renders reviewer scores', () => {
      render(
        <StepTracker
          steps={[step({ step: 7, step_name: 'reviewer', status: 'done', data: { avg_score: 8.4, files_reviewed: 6 } })]}
          totalSteps={9}
        />
      );
      expect(screen.getByText(/avg score 8\.4/)).toBeInTheDocument();
      expect(screen.getByText(/6 reviewed/)).toBeInTheDocument();
    });

    it('renders tester pass counts', () => {
      render(
        <StepTracker
          steps={[step({ step: 8, step_name: 'tester', status: 'done', data: { passed: 11, total: 14 } })]}
          totalSteps={9}
        />
      );
      expect(screen.getByText(/11\/14 passed/)).toBeInTheDocument();
    });

    it('puts a step error ahead of everything else in the payload', () => {
      render(
        <StepTracker
          steps={[step({ step: 6, step_name: 'debugger', status: 'failed', data: { error: 'timed out after 300s', elapsed_seconds: 300 } })]}
          totalSteps={9}
        />
      );
      expect(screen.getByText('timed out after 300s')).toBeInTheDocument();
    });

    it('renders no detail line when the payload is empty', () => {
      const { container } = render(
        <StepTracker steps={[step({ step: 2, step_name: 'planner', status: 'done', data: {} })]} totalSteps={9} />
      );
      expect(container.querySelector('.srow__msg')).not.toBeInTheDocument();
    });

    it('ignores the message field the backend never sends', () => {
      const { container } = render(
        <StepTracker
          steps={[step({ step: 2, step_name: 'planner', status: 'done', data: { message: 'not a real field' } })]}
          totalSteps={9}
        />
      );
      expect(container.querySelector('.srow__msg')).not.toBeInTheDocument();
    });
  });

  describe('progress meter', () => {
    it('reports completion as a percentage of the real step count', () => {
      render(
        <StepTracker
          steps={[
            step({ step: 1, step_name: 'intent_analyzer', status: 'done' }),
            step({ step: 2, step_name: 'planner', status: 'done' }),
            step({ step: 3, step_name: 'architect', status: 'running' }),
          ]}
          totalSteps={9}
        />
      );
      const bar = screen.getByRole('progressbar', { name: 'Pipeline progress' });
      // 2 of 9 done — the running step is not complete.
      expect(bar).toHaveAttribute('aria-valuenow', '22');
    });

    it('sits at zero before anything reports', () => {
      render(<StepTracker steps={[]} totalSteps={9} />);
      expect(screen.getByRole('progressbar', { name: 'Pipeline progress' }))
        .toHaveAttribute('aria-valuenow', '0');
    });
  });

  it('spins only the active step, never a completed one', () => {
    const { container } = render(
      <StepTracker
        steps={[
          step({ step: 1, step_name: 'intent_analyzer', status: 'done' }),
          step({ step: 2, step_name: 'planner', status: 'running' }),
        ]}
        totalSteps={9}
      />
    );
    // Exactly one looping element on the screen, tied to real in-flight work.
    expect(container.querySelectorAll('.spin-icon')).toHaveLength(1);
    const runningRow = container.querySelector('.srow--running')!;
    expect(within(runningRow as HTMLElement).getByText('running')).toBeInTheDocument();
  });
});
