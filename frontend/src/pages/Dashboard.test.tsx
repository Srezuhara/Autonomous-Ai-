import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Dashboard from './Dashboard';
import { renderPage, project, stats } from '../test/harness';
import { api } from '../api/client';

let listProjects: ReturnType<typeof vi.spyOn>;
let getStats: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  listProjects = vi.spyOn(api, 'listProjects');
  getStats = vi.spyOn(api, 'getStats');
  getStats.mockResolvedValue(stats() as never);
});

const envelope = (projects: unknown[], total = projects.length) =>
  ({ projects, total, limit: 50, offset: 0 }) as never;

describe('Dashboard', () => {
  describe('list states', () => {
    it('shows placeholders while loading', () => {
      listProjects.mockReturnValue(new Promise(() => {}) as never);
      const { container } = renderPage(<Dashboard />);
      expect(container.querySelector('[aria-busy]')).toBeInTheDocument();
      // Placeholders are inert panels, not looping shimmer.
      expect(container.querySelectorAll('.dash-skeleton').length).toBeGreaterThan(0);
    });

    it('shows the builds once they arrive', async () => {
      listProjects.mockResolvedValue(envelope([project(), project({ build_id: 'b2', app_name: 'Shortly' })]));
      renderPage(<Dashboard />);
      expect(await screen.findByText('TaskFlow')).toBeInTheDocument();
      expect(screen.getByText('Shortly')).toBeInTheDocument();
    });

    it('offers a retry when the backend is unreachable', async () => {
      listProjects.mockRejectedValue(new Error('Failed to fetch'));
      renderPage(<Dashboard />);
      expect(await screen.findByText('Backend unreachable')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    });

    it('invites a first build when there are none', async () => {
      listProjects.mockResolvedValue(envelope([]));
      renderPage(<Dashboard />);
      expect(await screen.findByText('No builds yet')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /Start a build/ })).toBeInTheDocument();
    });

    it('distinguishes an empty filter from an empty account', async () => {
      listProjects.mockResolvedValue(envelope([]));
      const { user } = { user: userEvent.setup() };
      renderPage(<Dashboard />);
      await screen.findByText('No builds yet');

      await user.click(screen.getByRole('button', { name: 'Failed' }));

      expect(await screen.findByText('Nothing in this state')).toBeInTheDocument();
      // And a way back, rather than a dead end.
      expect(screen.getByRole('button', { name: /View all builds/ })).toBeInTheDocument();
    });
  });

  describe('build count', () => {
    /**
     * `projects.length` is only ever the current page of 50, so it silently
     * under-reported past that. The envelope's `total` is the real count.
     */
    it('reports the envelope total, not the page length', async () => {
      listProjects.mockResolvedValue(envelope([project()], 137));
      renderPage(<Dashboard />);
      expect(await screen.findByText('137 builds')).toBeInTheDocument();
    });

    it('says "1 build", not "1 builds"', async () => {
      listProjects.mockResolvedValue(envelope([project()], 1));
      renderPage(<Dashboard />);
      expect(await screen.findByText('1 build')).toBeInTheDocument();
    });
  });

  describe('status filters', () => {
    it('offers every status a build can be in', async () => {
      listProjects.mockResolvedValue(envelope([]));
      renderPage(<Dashboard />);
      await screen.findByText('No builds yet');

      const group = screen.getByRole('group', { name: /Filter builds by status/ });
      for (const label of ['All', 'Running', 'Queued', 'Done', 'Partial', 'Failed', 'Cancelled']) {
        expect(within(group).getByRole('button', { name: label })).toBeInTheDocument();
      }
    });

    it('asks the API for the selected status', async () => {
      listProjects.mockResolvedValue(envelope([]));
      const user = userEvent.setup();
      renderPage(<Dashboard />);
      await screen.findByText('No builds yet');

      await user.click(screen.getByRole('button', { name: 'Cancelled' }));

      await waitFor(() => {
        expect(listProjects).toHaveBeenCalledWith(50, 0, 'cancelled');
      });
    });

    it('asks for everything when All is selected', async () => {
      listProjects.mockResolvedValue(envelope([]));
      renderPage(<Dashboard />);
      await screen.findByText('No builds yet');
      expect(listProjects).toHaveBeenCalledWith(50, 0, undefined);
    });

    it('marks exactly one filter as pressed', async () => {
      listProjects.mockResolvedValue(envelope([]));
      const user = userEvent.setup();
      renderPage(<Dashboard />);
      await screen.findByText('No builds yet');

      await user.click(screen.getByRole('button', { name: 'Running' }));

      const group = screen.getByRole('group', { name: /Filter builds by status/ });
      const pressed = within(group).getAllByRole('button')
        .filter(b => b.getAttribute('aria-pressed') === 'true');
      expect(pressed).toHaveLength(1);
      expect(pressed[0]).toHaveAccessibleName('Running');
    });
  });

  describe('KPI row', () => {
    it('renders the platform stats', async () => {
      listProjects.mockResolvedValue(envelope([]));
      renderPage(<Dashboard />);
      expect(await screen.findByText('42')).toBeInTheDocument();      // total builds
      expect(screen.getByText('76.2')).toBeInTheDocument();            // success rate
      expect(screen.getByText('361')).toBeInTheDocument();             // avg duration
      expect(screen.getByText('web_app')).toBeInTheDocument();         // top type
    });

    it('shows an em dash rather than NaN when duration is unknown', async () => {
      // Reading only the nested `duration_seconds.average` used to produce
      // Math.round(undefined) here.
      getStats.mockResolvedValue(
        stats({ avg_duration_seconds: null, duration_seconds: { average: null, min: null, max: null } }) as never
      );
      listProjects.mockResolvedValue(envelope([]));
      renderPage(<Dashboard />);
      await screen.findByText('42');
      expect(screen.getAllByText('—').length).toBeGreaterThan(0);
      expect(screen.queryByText('NaN')).not.toBeInTheDocument();
    });

    it('falls back to the nested average for an older backend', async () => {
      getStats.mockResolvedValue(
        stats({ avg_duration_seconds: undefined, duration_seconds: { average: 240, min: 1, max: 2 } }) as never
      );
      listProjects.mockResolvedValue(envelope([]));
      renderPage(<Dashboard />);
      expect(await screen.findByText('240')).toBeInTheDocument();
    });
  });

  it('does not duplicate the sidebar\'s New Build action', async () => {
    listProjects.mockResolvedValue(envelope([project()]));
    renderPage(<Dashboard />);
    await screen.findByText('TaskFlow');
    // The sidebar pins that action on every screen; a second copy in the header
    // was competing with it.
    expect(screen.queryByRole('link', { name: /New build/i })).not.toBeInTheDocument();
  });

  it('refetches on demand', async () => {
    listProjects.mockResolvedValue(envelope([project()]));
    const user = userEvent.setup();
    renderPage(<Dashboard />);
    await screen.findByText('TaskFlow');

    const before = listProjects.mock.calls.length;
    await user.click(screen.getByRole('button', { name: /Refresh builds/ }));
    await waitFor(() => expect(listProjects.mock.calls.length).toBeGreaterThan(before));
  });
});
