import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusBadge } from './StatusBadge';

/**
 * Every status string the backend can put in the `status` column must map to a
 * designed badge. `pending` did not, and fell through to a default that
 * rendered the raw lowercase string — the only badge in the product that was
 * not a designed one.
 *
 * The list below is `BuildStatus` in api/client.ts. If a status is added there
 * and not here, that is the bug this file exists to catch.
 */
const ALL_STATUSES = [
  'pending',
  'queued',
  'running',
  'done',
  'done_with_context',
  'failed',
  'cancelled',
] as const;

describe('StatusBadge', () => {
  it.each(ALL_STATUSES)('renders a designed badge for %s', (status) => {
    const { container } = render(<StatusBadge status={status} />);
    const badge = container.querySelector('.badge');

    expect(badge).toBeInTheDocument();

    // A designed badge always carries a second, semantic class. Falling through
    // to the default is what we are guarding against.
    const classes = Array.from(badge!.classList);
    expect(classes.some(c => c.startsWith('badge-'))).toBe(true);

    // And it never prints the raw snake_case status back at the user.
    expect(badge!.textContent).not.toBe(status);
  });

  it('gives cancelled a neutral badge, not an error one', () => {
    // A user-stopped build did not fail. Status colour is reserved vocabulary,
    // and the charts render cancelled achromatically — an error-red badge here
    // would tell a different story about the same state.
    const { container } = render(<StatusBadge status="cancelled" />);
    expect(container.querySelector('.badge-neutral')).toBeInTheDocument();
    expect(container.querySelector('.badge-error')).not.toBeInTheDocument();
  });

  it('gives done_with_context a warning badge, not an error one', () => {
    // Phase 21: the build produced downloadable code. It is degraded, not dead.
    const { container } = render(<StatusBadge status="done_with_context" />);
    expect(container.querySelector('.badge-warning')).toBeInTheDocument();
    expect(container.querySelector('.badge-error')).not.toBeInTheDocument();
  });

  it('does not colour running as info-blue', () => {
    // The validated chart palette dropped blue entirely (0.7 deltaE against the
    // brand violet under deuteranopia), so a blue running badge beside a violet
    // running chart segment would disagree with itself.
    const { container } = render(<StatusBadge status="running" />);
    expect(container.querySelector('.badge-accent')).toBeInTheDocument();
    expect(container.querySelector('.badge-info')).not.toBeInTheDocument();
  });

  it('still renders something for an unknown status', () => {
    // Forward compatibility: a status this build has never heard of should
    // degrade to a readable chip rather than crashing the row it sits in.
    render(<StatusBadge status="some_future_status" />);
    expect(screen.getByText('some_future_status')).toBeInTheDocument();
  });
});
