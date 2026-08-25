import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import NewBuild from './NewBuild';
import { renderPage } from '../test/harness';
import { api } from '../api/client';
import { MAX_CHARS, MIN_CHARS } from '../lib/prompt';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

let createProject: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  mockNavigate.mockReset();
  createProject = vi.spyOn(api, 'createProject');
});

const field = () => screen.getByLabelText(/Your app/);
const submit = () => screen.getByRole('button', { name: /Build app/ });

describe('NewBuild', () => {
  describe('submit guard', () => {
    it('starts disabled with an empty field', () => {
      renderPage(<NewBuild />);
      expect(submit()).toBeDisabled();
    });

    it('stays disabled below the minimum length', async () => {
      const user = userEvent.setup();
      renderPage(<NewBuild />);
      await user.type(field(), 'a'.repeat(MIN_CHARS - 1));
      expect(submit()).toBeDisabled();
    });

    it('enables at the minimum length', async () => {
      const user = userEvent.setup();
      renderPage(<NewBuild />);
      await user.type(field(), 'a'.repeat(MIN_CHARS));
      expect(submit()).toBeEnabled();
    });

    it('disables again past the character limit', async () => {
      const user = userEvent.setup();
      renderPage(<NewBuild />);
      await user.click(field());
      await user.paste('a'.repeat(MAX_CHARS + 1));
      expect(submit()).toBeDisabled();
    });

    it('does not count whitespace toward the minimum', async () => {
      const user = userEvent.setup();
      renderPage(<NewBuild />);
      await user.type(field(), '          ');
      expect(submit()).toBeDisabled();
    });
  });

  describe('readout', () => {
    it('prompts the user before they type', () => {
      renderPage(<NewBuild />);
      expect(screen.getByText('Describe what you want built')).toBeInTheDocument();
    });

    it('counts up to the minimum', async () => {
      const user = userEvent.setup();
      renderPage(<NewBuild />);
      await user.type(field(), 'abc');
      expect(screen.getByText(`${MIN_CHARS - 3} more characters to start`)).toBeInTheDocument();
    });

    it('reports the budget once usable', async () => {
      const user = userEvent.setup();
      renderPage(<NewBuild />);
      await user.type(field(), 'a'.repeat(20));
      expect(screen.getByText(`20 / ${MAX_CHARS}`)).toBeInTheDocument();
    });

    it('says how far over the limit the prompt is', async () => {
      const user = userEvent.setup();
      renderPage(<NewBuild />);
      await user.click(field());
      await user.paste('a'.repeat(MAX_CHARS + 5));
      expect(screen.getByText(`5 over the ${MAX_CHARS} limit`)).toBeInTheDocument();
    });

    it('is announced politely rather than interrupting', () => {
      const { container } = renderPage(<NewBuild />);
      expect(container.querySelector('[aria-live="polite"]')).toBeInTheDocument();
    });
  });

  describe('submission', () => {
    it('sends the trimmed prompt and navigates to the build', async () => {
      createProject.mockResolvedValue({ build_id: 'new-build-id', status: 'queued' } as never);
      const user = userEvent.setup();
      renderPage(<NewBuild />);

      await user.type(field(), '  A FastAPI URL shortener  ');
      await user.click(submit());

      await waitFor(() => expect(createProject).toHaveBeenCalledWith('A FastAPI URL shortener'));
      await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/build/new-build-id'));
    });

    it('submits on Ctrl+Enter', async () => {
      createProject.mockResolvedValue({ build_id: 'x1', status: 'queued' } as never);
      const user = userEvent.setup();
      renderPage(<NewBuild />);

      await user.type(field(), 'A FastAPI URL shortener');
      await user.keyboard('{Control>}{Enter}{/Control}');

      await waitFor(() => expect(createProject).toHaveBeenCalled());
    });

    it('ignores Ctrl+Enter while the guard is failing', async () => {
      const user = userEvent.setup();
      renderPage(<NewBuild />);
      await user.type(field(), 'short');
      await user.keyboard('{Control>}{Enter}{/Control}');
      expect(createProject).not.toHaveBeenCalled();
    });

    it('accepts a full 2000-character prompt', async () => {
      // The limit the backend now agrees with. This used to 422.
      createProject.mockResolvedValue({ build_id: 'x2', status: 'queued' } as never);
      const user = userEvent.setup();
      renderPage(<NewBuild />);

      await user.click(field());
      await user.paste('a'.repeat(MAX_CHARS));
      expect(submit()).toBeEnabled();

      await user.click(submit());
      await waitFor(() => {
        expect((createProject.mock.calls[0][0] as string).length).toBe(MAX_CHARS);
      });
    });

    it('surfaces a failure and lets the user try again', async () => {
      createProject.mockRejectedValue(new Error('Backend unreachable'));
      const user = userEvent.setup();
      renderPage(<NewBuild />);

      await user.type(field(), 'A FastAPI URL shortener');
      await user.click(submit());

      expect(await screen.findByRole('alert')).toHaveTextContent('Backend unreachable');
      // Not left in a permanently-submitting state.
      await waitFor(() => expect(submit()).toBeEnabled());
      expect(mockNavigate).not.toHaveBeenCalled();
    });

    it('locks the field while the request is in flight', async () => {
      createProject.mockReturnValue(new Promise(() => {}) as never);
      const user = userEvent.setup();
      renderPage(<NewBuild />);

      await user.type(field(), 'A FastAPI URL shortener');
      await user.click(submit());

      await waitFor(() => expect(field()).toBeDisabled());
      expect(screen.getByText(/Launching agents/)).toBeInTheDocument();
    });
  });

  describe('examples', () => {
    it('fills the field from an example chip', async () => {
      const user = userEvent.setup();
      renderPage(<NewBuild />);
      await user.click(screen.getByRole('button', { name: /REST API/ }));
      // `toHaveValue` compares exactly, so read the value and match on it.
      expect((field() as HTMLTextAreaElement).value).toContain('FastAPI');
    });
  });

  describe('clear', () => {
    it('appears only once there is something to clear', async () => {
      const user = userEvent.setup();
      renderPage(<NewBuild />);
      expect(screen.queryByRole('button', { name: /Clear prompt/ })).not.toBeInTheDocument();

      await user.type(field(), 'abc');
      await user.click(screen.getByRole('button', { name: /Clear prompt/ }));

      expect(field()).toHaveValue('');
    });
  });

  it('names slot 9 Documenter in the pipeline rail', () => {
    // The rail claims to preview the exact list the user watches next, so a
    // name that does not exist in the pipeline makes it a lie.
    renderPage(<NewBuild />);
    expect(screen.getByText('Documenter')).toBeInTheDocument();
    expect(screen.queryByText('Packager')).not.toBeInTheDocument();
  });
});
