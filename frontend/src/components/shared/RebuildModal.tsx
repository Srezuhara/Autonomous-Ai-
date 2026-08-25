import { useState, useRef, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { X, RefreshCw, Sparkles, Plus } from 'lucide-react';
import { dialogIn, backdropIn } from '../../lib/motion';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { PromptComposer } from './PromptComposer';
import { promptState } from '../../lib/prompt';
import './RebuildModal.css';

interface RebuildModalProps {
  isOpen:         boolean;
  onClose:        () => void;
  onRebuild:      (customPrompt: string) => void;
  originalPrompt: string;
  appName:        string;
  isRebuilding:   boolean;
}

/**
 * RebuildModal — re-run the pipeline, optionally with new instructions.
 *
 * Rewritten off a 260-line CSS-in-JS template literal that was injected into
 * the document through a `<style>` tag on every mount. That literal was a
 * second stylesheet: its own chip vocabulary, its own tab vocabulary,
 * hardcoded rgba throughout, and `transition: all` on several rules. All of it
 * is now RebuildModal.css built from `.panel` / `.chip` / `.ulabel` / `.btn`.
 *
 * It was also not a dialog in any accessible sense — no `role`, no
 * `aria-modal`, no focus trap, no Escape handler and no focus restoration.
 * `useFocusTrap` supplies the last three; the roles are below.
 *
 * The custom-instruction field is the same `PromptComposer` as NewBuild, so
 * both textareas in the product enforce the same 2000-character contract. The
 * old one counted down from 500 while the API rejected above 500 with a 422 —
 * two different wrong numbers on one screen.
 *
 * Enter and exit are both real. The first version returned `null` when closed,
 * so a full-viewport blurred overlay was deleted between two frames — the most
 * abrupt state change in the product, on a confirmation flow. `AnimatePresence`
 * holds it mounted long enough to fade, and the exit is subtler than the enter
 * (opacity only, shorter) so it recedes rather than retracing its arrival.
 */

const REBUILD_SUGGESTIONS = [
  'Add user authentication with JWT tokens',
  'Improve error handling and add input validation',
  'Add a database with SQLite and persist data',
  'Make the UI more responsive and mobile-friendly',
  'Add real-time updates with WebSockets',
  'Improve test coverage and add integration tests',
  'Add pagination, filtering, and search',
  'Add API rate limiting and security headers',
];

const MODES = [
  { value: 'same',   label: 'Same prompt',         icon: RefreshCw },
  { value: 'custom', label: 'Custom instructions', icon: Sparkles  },
] as const;

type Mode = (typeof MODES)[number]['value'];

export function RebuildModal({
  isOpen,
  onClose,
  onRebuild,
  originalPrompt,
  appName,
  isRebuilding,
}: RebuildModalProps) {
  const [mode, setMode] = useState<Mode>('same');
  const [customPrompt, setCustomPrompt] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const dialogRef = useFocusTrap<HTMLDivElement>(isOpen, onClose);

  // Switching to the custom tab hands focus to the field it just revealed.
  // Nothing here sets state, so it does not cascade a render the way the old
  // reset-on-close effect did.
  useEffect(() => {
    if (isOpen && mode === 'custom') textareaRef.current?.focus();
  }, [isOpen, mode]);

  // While the dialog is up the page behind it must not scroll under the
  // overlay — on touch especially, that reads as the modal drifting.
  useEffect(() => {
    if (!isOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previous; };
  }, [isOpen]);

  const { isValid } = promptState(customPrompt);
  const canSubmit = !isRebuilding && (mode === 'same' || isValid);

  const handleSubmit = () => {
    if (!canSubmit) return;
    onRebuild(mode === 'same' ? '' : customPrompt.trim());
  };

  /**
   * The state reset lives here rather than in an effect keyed on `isOpen`.
   * That effect ran on every close and set two pieces of state during the
   * commit, which is the cascading-render pattern the React lint rule flags;
   * doing it on the way out is both cheaper and easier to follow.
   */
  const handleClose = () => {
    setMode('same');
    setCustomPrompt('');
    onClose();
  };

  const addSuggestion = (text: string) => {
    setCustomPrompt(prev => (prev ? `${prev}\n${text}` : text));
    textareaRef.current?.focus();
  };

  return (
    <AnimatePresence>
      {isOpen && (
      <motion.div
        className="modal-backdrop"
        onMouseDown={e => { if (e.target === e.currentTarget) handleClose(); }}
        variants={backdropIn}
        initial="hidden"
        animate="visible"
        exit="exit"
      >
      <motion.div
        ref={dialogRef}
        className="panel rebuild"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rebuild-title"
        tabIndex={-1}
        variants={dialogIn}
        initial="hidden"
        animate="visible"
        exit="exit"
      >
        <header className="rebuild__head">
          <div className="rebuild__title-row">
            <RefreshCw size={16} className="rebuild__title-icon" aria-hidden />
            <h2 id="rebuild-title" className="rebuild__title">
              Rebuild <em>{appName}</em>
            </h2>
          </div>
          <button
            className="btn btn-ghost btn-icon"
            onClick={handleClose}
            aria-label="Close dialog"
            disabled={isRebuilding}
          >
            <X size={16} />
          </button>
        </header>

        <div className="rebuild__modes" role="group" aria-label="Rebuild mode">
          {MODES.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              type="button"
              className="chip"
              aria-pressed={mode === value}
              onClick={() => setMode(value)}
              disabled={isRebuilding}
            >
              <Icon size={12} strokeWidth={2} />
              {label}
            </button>
          ))}
        </div>

        <div className="rebuild__body">
          {mode === 'same' ? (
            <>
              <p className="rebuild__lede">
                The pipeline re-runs all nine agents from scratch against the
                original prompt — useful for a fresh build after a failure, or
                after the pipeline itself has improved.
              </p>
              <div className="rebuild__quote">
                <span className="ulabel">Original prompt</span>
                <p>{originalPrompt}</p>
              </div>
            </>
          ) : (
            <>
              <PromptComposer
                ref={textareaRef}
                id="rebuild-prompt-input"
                /* `.panel` is what carries the border and the focus-within
                   ring. Without it this field had NO visible focus indicator
                   at all: the composer suppresses the textarea's own outline
                   on the assumption that its surface lights up instead, and
                   that assumption only holds when the caller supplies one. */
                className="panel"
                label="What should change"
                value={customPrompt}
                onChange={setCustomPrompt}
                onSubmit={handleSubmit}
                disabled={isRebuilding}
                minHeight={132}
                idleText="Describe what you want changed"
                placeholder={
                  'Keep the same task manager, but add user accounts, persist '
                  + 'tasks in SQLite, and tighten up the input validation…'
                }
              />

              <div className="rebuild__suggestions">
                <span className="ulabel">Quick add</span>
                <div className="rebuild__suggestion-row">
                  {REBUILD_SUGGESTIONS.map(s => (
                    <button
                      key={s}
                      type="button"
                      className="chip"
                      onClick={() => addSuggestion(s)}
                      disabled={isRebuilding}
                    >
                      <Plus size={11} strokeWidth={2} />
                      {s}
                    </button>
                  ))}
                </div>
              </div>

              <details className="rebuild__ref">
                <summary>View original prompt</summary>
                <p>{originalPrompt}</p>
              </details>
            </>
          )}
        </div>

        <footer className="rebuild__foot">
          <button className="btn btn-secondary" onClick={handleClose} disabled={isRebuilding}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={!canSubmit}>
            {isRebuilding
              ? <><div className="spinner" /> Launching rebuild…</>
              : <><RefreshCw size={14} /> Start rebuild</>
            }
          </button>
        </footer>
      </motion.div>
      </motion.div>
      )}
    </AnimatePresence>
  );
}
