import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import ProjectDetail from './ProjectDetail';
import { renderPage, project } from '../test/harness';
import { api } from '../api/client';

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useParams: () => ({ id: 'fb3e4b24-5491-4925-bdb2-4a096df4735f' }),
    useNavigate: () => vi.fn(),
  };
});

let getProject: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  getProject = vi.spyOn(api, 'getProject');
});

const detail = (over: Record<string, unknown> = {}) =>
  ({ ...project(), files: ['main.py', 'README.md'], file_count: 2, ...over }) as never;

describe('ProjectDetail', () => {
  describe('page states', () => {
    it('holds space while loading', () => {
      getProject.mockReturnValue(new Promise(() => {}) as never);
      const { container } = renderPage(<ProjectDetail />);
      expect(container.querySelectorAll('.pd-skeleton').length).toBeGreaterThan(0);
    });

    it('explains a missing build and offers a way back', async () => {
      getProject.mockRejectedValue(new Error('404'));
      renderPage(<ProjectDetail />);
      expect(await screen.findByText('Build not found')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /Back to dashboard/ })).toBeInTheDocument();
    });

    it('uses the shared empty-state vocabulary', async () => {
      // `.empty-state` was pruned from globals while this state still used it,
      // so it rendered completely unstyled. See src/test/classes.test.ts.
      getProject.mockRejectedValue(new Error('404'));
      const { container } = renderPage(<ProjectDetail />);
      await screen.findByText('Build not found');
      expect(container.querySelector('.empty')).toBeInTheDocument();
      expect(container.querySelector('.empty__title')).toBeInTheDocument();
    });

    it('renders the report once loaded', async () => {
      getProject.mockResolvedValue(detail());
      renderPage(<ProjectDetail />);
      expect(await screen.findByText('TaskFlow')).toBeInTheDocument();
    });
  });

  describe('scores', () => {
    it('renders all three, each in its native format', async () => {
      getProject.mockResolvedValue(detail({ review_score: 8.4, debug_score: '9/10', test_score: '3/5' }));
      renderPage(<ProjectDetail />);
      await screen.findByText('TaskFlow');
      expect(screen.getByText('8.4')).toBeInTheDocument();
      expect(screen.getByText('9/10')).toBeInTheDocument();
      expect(screen.getByText('3/5')).toBeInTheDocument();
    });

    it('exposes each score as a labelled progress bar', async () => {
      getProject.mockResolvedValue(detail());
      renderPage(<ProjectDetail />);
      await screen.findByText('TaskFlow');
      // "3/5" is 60% — the fraction is interpreted, not truncated to "3".
      expect(screen.getByRole('progressbar', { name: /test/i })).toHaveAttribute('aria-valuenow', '60');
    });

    it('shows an em dash for a score the build never produced', async () => {
      getProject.mockResolvedValue(detail({ test_score: undefined }));
      renderPage(<ProjectDetail />);
      await screen.findByText('TaskFlow');
      expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    });
  });

  describe('degraded builds', () => {
    it('surfaces completion_reason for a done_with_context build', async () => {
      getProject.mockResolvedValue(detail({
        status: 'done_with_context',
        completion_reason: 'Daily quota exhausted after step 7',
      }));
      renderPage(<ProjectDetail />);
      expect(await screen.findByText(/Daily quota exhausted after step 7/)).toBeInTheDocument();
    });

    it('still offers the download — the code exists', async () => {
      getProject.mockResolvedValue(detail({ status: 'done_with_context' }));
      renderPage(<ProjectDetail />);
      await screen.findByText('TaskFlow');
      expect(screen.getByRole('button', { name: /Download/i })).toBeInTheDocument();
    });

    it('offers no download for a failed build', async () => {
      getProject.mockResolvedValue(detail({ status: 'failed' }));
      renderPage(<ProjectDetail />);
      await screen.findByText('TaskFlow');
      expect(screen.queryByRole('button', { name: /Download/i })).not.toBeInTheDocument();
    });
  });

  describe('rebuild', () => {
    it('opens the dialog from the toolbar', async () => {
      const { default: userEvent } = await import('@testing-library/user-event');
      getProject.mockResolvedValue(detail());
      const user = userEvent.setup();
      renderPage(<ProjectDetail />);
      await screen.findByText('TaskFlow');

      await user.click(screen.getByRole('button', { name: /Rebuild/i }));
      expect(await screen.findByRole('dialog')).toBeInTheDocument();
    });
  });
});
