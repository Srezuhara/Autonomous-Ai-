import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RebuildModal } from './RebuildModal';
import { MAX_CHARS, MIN_CHARS } from '../../lib/prompt';

function setup(over: Partial<Parameters<typeof RebuildModal>[0]> = {}) {
  const onClose = vi.fn();
  const onRebuild = vi.fn();
  const props = {
    isOpen: true,
    onClose,
    onRebuild,
    originalPrompt: 'Build a task manager with drag and drop',
    appName: 'TaskFlow',
    isRebuilding: false,
    ...over,
  };
  const utils = render(<RebuildModal {...props} />);
  return { ...utils, onClose, onRebuild, user: userEvent.setup() };
}

describe('RebuildModal', () => {
  it('renders nothing when closed', () => {
    setup({ isOpen: false });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  describe('accessibility', () => {
    /**
     * The original had none of this — no role, no aria-modal, no focus trap,
     * no Escape handler and no focus restoration.
     */
    it('is a labelled modal dialog', () => {
      setup();
      const dialog = screen.getByRole('dialog');
      expect(dialog).toHaveAttribute('aria-modal', 'true');
      expect(dialog).toHaveAccessibleName(/Rebuild/);
    });

    it('moves focus into the dialog on open', async () => {
      setup();
      await waitFor(() => {
        expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true);
      });
    });

    it('closes on Escape', async () => {
      const { onClose, user } = setup();
      await user.keyboard('{Escape}');
      expect(onClose).toHaveBeenCalled();
    });

    it('returns focus to the trigger when it closes', async () => {
      const trigger = document.createElement('button');
      trigger.textContent = 'Rebuild';
      document.body.appendChild(trigger);
      trigger.focus();
      expect(document.activeElement).toBe(trigger);

      const { rerender } = render(
        <RebuildModal
          isOpen onClose={() => {}} onRebuild={() => {}}
          originalPrompt="p" appName="TaskFlow" isRebuilding={false}
        />
      );
      await waitFor(() => expect(document.activeElement).not.toBe(trigger));

      rerender(
        <RebuildModal
          isOpen={false} onClose={() => {}} onRebuild={() => {}}
          originalPrompt="p" appName="TaskFlow" isRebuilding={false}
        />
      );
      await waitFor(() => expect(document.activeElement).toBe(trigger));

      trigger.remove();
    });

    it('keeps Tab inside the dialog', async () => {
      // An outside control that Tab must never reach while the dialog is up.
      const outside = document.createElement('button');
      outside.textContent = 'Outside';
      document.body.appendChild(outside);

      const { user } = setup();
      const dialog = screen.getByRole('dialog');

      for (let i = 0; i < 12; i++) {
        await user.tab();
        expect(dialog.contains(document.activeElement)).toBe(true);
      }

      outside.remove();
    });
  });

  describe('same-prompt mode', () => {
    it('opens on same-prompt and shows the original', () => {
      setup();
      expect(screen.getByRole('button', { name: /Same prompt/ })).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByText('Build a task manager with drag and drop')).toBeInTheDocument();
    });

    it('submits an empty custom prompt', async () => {
      const { onRebuild, user } = setup();
      await user.click(screen.getByRole('button', { name: /Start rebuild/ }));
      expect(onRebuild).toHaveBeenCalledWith('');
    });

    it('can submit immediately — there is nothing to type', () => {
      setup();
      expect(screen.getByRole('button', { name: /Start rebuild/ })).toBeEnabled();
    });
  });

  describe('custom-instruction mode', () => {
    it('switches to the composer', async () => {
      const { user } = setup();
      await user.click(screen.getByRole('button', { name: /Custom instructions/ }));
      expect(screen.getByLabelText(/What should change/)).toBeInTheDocument();
    });

    it('blocks submit until the prompt is long enough', async () => {
      const { user } = setup();
      await user.click(screen.getByRole('button', { name: /Custom instructions/ }));
      const submit = screen.getByRole('button', { name: /Start rebuild/ });

      expect(submit).toBeDisabled();

      await user.type(screen.getByLabelText(/What should change/), 'a'.repeat(MIN_CHARS - 1));
      expect(submit).toBeDisabled();

      await user.type(screen.getByLabelText(/What should change/), 'a');
      expect(submit).toBeEnabled();
    });

    it('submits the trimmed custom prompt', async () => {
      const { onRebuild, user } = setup();
      await user.click(screen.getByRole('button', { name: /Custom instructions/ }));
      await user.type(screen.getByLabelText(/What should change/), '  Add JWT authentication please  ');
      await user.click(screen.getByRole('button', { name: /Start rebuild/ }));
      expect(onRebuild).toHaveBeenCalledWith('Add JWT authentication please');
    });

    it('enforces the same 2000-char contract as NewBuild', async () => {
      const { user } = setup();
      await user.click(screen.getByRole('button', { name: /Custom instructions/ }));
      const field = screen.getByLabelText(/What should change/);

      // Paste rather than type — 2001 keystrokes is not a test, it's a wait.
      await user.click(field);
      await user.paste('a'.repeat(MAX_CHARS + 1));

      expect(screen.getByText(`1 over the ${MAX_CHARS} limit`)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Start rebuild/ })).toBeDisabled();
    });

    it('appends a quick-add suggestion to what is already there', async () => {
      const { user } = setup();
      await user.click(screen.getByRole('button', { name: /Custom instructions/ }));
      await user.type(screen.getByLabelText(/What should change/), 'First line');
      await user.click(screen.getByRole('button', { name: /Add user authentication with JWT tokens/ }));

      expect(screen.getByLabelText(/What should change/))
        .toHaveValue('First line\nAdd user authentication with JWT tokens');
    });

    it('submits on Ctrl+Enter', async () => {
      const { onRebuild, user } = setup();
      await user.click(screen.getByRole('button', { name: /Custom instructions/ }));
      await user.type(screen.getByLabelText(/What should change/), 'Add JWT authentication');
      await user.keyboard('{Control>}{Enter}{/Control}');
      expect(onRebuild).toHaveBeenCalledWith('Add JWT authentication');
    });
  });

  describe('while a rebuild is in flight', () => {
    it('disables every control so the request cannot be sent twice', () => {
      setup({ isRebuilding: true });
      expect(screen.getByRole('button', { name: /Launching rebuild/ })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
      expect(screen.getByRole('button', { name: /Close dialog/ })).toBeDisabled();
    });

    it('shows the one sanctioned spinner beside real in-flight work', () => {
      const { container } = setup({ isRebuilding: true });
      expect(container.querySelectorAll('.spinner')).toHaveLength(1);
      // And a text alternative for anyone who has motion turned off.
      expect(screen.getByText(/Launching rebuild/)).toBeInTheDocument();
    });
  });

  describe('dismissal', () => {
    it('closes on the Cancel button', async () => {
      const { onClose, user } = setup();
      await user.click(screen.getByRole('button', { name: 'Cancel' }));
      expect(onClose).toHaveBeenCalled();
    });

    it('closes on a backdrop click', async () => {
      const { onClose, container } = setup();
      const backdrop = container.querySelector('.modal-backdrop')!;
      // mousedown on the backdrop itself, not on the dialog inside it.
      await userEvent.setup().pointer({ target: backdrop, keys: '[MouseLeft]' });
      expect(onClose).toHaveBeenCalled();
    });

    it('does not close when the click started inside the dialog', async () => {
      const { onClose, user } = setup();
      await user.click(screen.getByText(/The pipeline re-runs all nine agents/));
      expect(onClose).not.toHaveBeenCalled();
    });
  });
});
