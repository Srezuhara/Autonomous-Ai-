import { useState, useRef, useEffect } from 'react';
import { X, RefreshCw, Sparkles, ChevronRight } from 'lucide-react';

interface RebuildModalProps {
  isOpen:        boolean;
  onClose:       () => void;
  onRebuild:     (customPrompt: string) => void;
  originalPrompt: string;
  appName:       string;
  isRebuilding:  boolean;
}

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

export function RebuildModal({
  isOpen,
  onClose,
  onRebuild,
  originalPrompt,
  appName,
  isRebuilding,
}: RebuildModalProps) {
  const [mode, setMode]               = useState<'same' | 'custom'>('same');
  const [customPrompt, setCustomPrompt] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (isOpen && mode === 'custom') {
      setTimeout(() => textareaRef.current?.focus(), 100);
    }
  }, [isOpen, mode]);

  useEffect(() => {
    if (!isOpen) {
      setMode('same');
      setCustomPrompt('');
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = () => {
    if (mode === 'same') {
      onRebuild('');
    } else {
      if (!customPrompt.trim()) return;
      onRebuild(customPrompt.trim());
    }
  };

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose();
  };

  const canSubmit = !isRebuilding && (mode === 'same' || customPrompt.trim().length > 10);

  return (
    <div className="modal-backdrop" onClick={handleBackdropClick}>
      <div className="rebuild-modal">

        {/* Header */}
        <div className="rebuild-modal-header">
          <div className="rebuild-modal-title-row">
            <RefreshCw size={18} style={{ color: 'var(--color-accent-secondary)' }} />
            <h2 className="rebuild-modal-title">Rebuild <span>{appName}</span></h2>
          </div>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>

        {/* Mode selector */}
        <div className="rebuild-mode-tabs">
          <button
            className={`rebuild-mode-tab${mode === 'same' ? ' active' : ''}`}
            onClick={() => setMode('same')}
          >
            <RefreshCw size={14} />
            Same Prompt
          </button>
          <button
            className={`rebuild-mode-tab${mode === 'custom' ? ' active' : ''}`}
            onClick={() => setMode('custom')}
          >
            <Sparkles size={14} />
            Custom Instructions
          </button>
        </div>

        {/* Content */}
        {mode === 'same' ? (
          <div className="rebuild-same-content">
            <p className="rebuild-same-label">Will rebuild using the original prompt:</p>
            <div className="rebuild-original-prompt">
              <p>{originalPrompt}</p>
            </div>
            <p className="rebuild-same-note">
              The pipeline will re-run all 9 agents from scratch with the same requirements.
              Useful for getting a fresh build after bugs or improvements to the pipeline itself.
            </p>
          </div>
        ) : (
          <div className="rebuild-custom-content">
            <p className="rebuild-same-label">Describe what you want changed or improved:</p>
            <textarea
              ref={textareaRef}
              className="rebuild-textarea"
              placeholder={`e.g. "Keep the same task manager but add user authentication, a SQLite database to persist tasks, and improve the UI with better colors and animations"`}
              value={customPrompt}
              onChange={e => setCustomPrompt(e.target.value)}
              rows={5}
            />
            <p className="rebuild-char-count" style={{
              color: customPrompt.length > 450 ? 'var(--color-warning)' : 'var(--text-tertiary)'
            }}>
              {500 - customPrompt.length} chars remaining
            </p>

            {/* Quick suggestions */}
            <div className="rebuild-suggestions">
              <p className="rebuild-suggestions-label">Quick add:</p>
              <div className="rebuild-suggestions-list">
                {REBUILD_SUGGESTIONS.map(s => (
                  <button
                    key={s}
                    className="rebuild-suggestion-chip"
                    onClick={() => setCustomPrompt(prev =>
                      prev ? `${prev}\n${s}` : s
                    )}
                  >
                    <ChevronRight size={11} />
                    {s}
                  </button>
                ))}
              </div>
            </div>

            {/* Original prompt reference */}
            <details className="rebuild-original-ref">
              <summary>View original prompt</summary>
              <p>{originalPrompt}</p>
            </details>
          </div>
        )}

        {/* Footer */}
        <div className="rebuild-modal-footer">
          <button className="btn btn-secondary" onClick={onClose} disabled={isRebuilding}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={!canSubmit}
          >
            {isRebuilding
              ? <><div className="spinner" /> Launching rebuild…</>
              : <><RefreshCw size={14} /> Start Rebuild</>
            }
          </button>
        </div>
      </div>

      <style>{MODAL_CSS}</style>
    </div>
  );
}

const MODAL_CSS = `
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(8px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  animation: backdropIn 0.2s ease-out;
}

@keyframes backdropIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}

.rebuild-modal {
  background: var(--color-bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: 20px;
  width: 100%;
  max-width: 600px;
  display: flex;
  flex-direction: column;
  gap: 0;
  box-shadow: 0 24px 80px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.05);
  animation: modalIn 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
}

@keyframes modalIn {
  from { opacity: 0; transform: translateY(16px) scale(0.97); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

.rebuild-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--border-subtle);
}

.rebuild-modal-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.rebuild-modal-title {
  font-size: 1.125rem;
  font-weight: 700;
  color: var(--text-primary);
  font-family: var(--font-display);
  letter-spacing: -0.02em;
}

.rebuild-modal-title span {
  color: var(--color-accent-secondary);
}

/* Mode tabs */
.rebuild-mode-tabs {
  display: flex;
  gap: 4px;
  padding: 12px 24px;
  background: var(--color-bg-surface);
  border-bottom: 1px solid var(--border-subtle);
}

.rebuild-mode-tab {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 16px;
  border-radius: 10px;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-tertiary);
  background: transparent;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s ease;
}

.rebuild-mode-tab:hover {
  color: var(--text-secondary);
  background: var(--color-bg-hover);
}

.rebuild-mode-tab.active {
  color: var(--text-primary);
  background: var(--color-bg-elevated);
  border-color: var(--border-accent);
  box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}

/* Same mode */
.rebuild-same-content {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.rebuild-same-label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-tertiary);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.rebuild-original-prompt {
  background: var(--color-bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 14px 16px;
}

.rebuild-original-prompt p {
  font-size: 0.875rem;
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0;
}

.rebuild-same-note {
  font-size: 0.8125rem;
  color: var(--text-tertiary);
  line-height: 1.6;
  margin: 0;
}

/* Custom mode */
.rebuild-custom-content {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 70vh;
  overflow-y: auto;
}

.rebuild-textarea {
  width: 100%;
  background: var(--color-bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 12px 14px;
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 0.9rem;
  line-height: 1.6;
  resize: vertical;
  min-height: 100px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  outline: none;
}

.rebuild-textarea:focus {
  border-color: var(--border-accent);
  box-shadow: 0 0 0 1px var(--border-accent), var(--shadow-glow);
}

.rebuild-textarea::placeholder {
  color: var(--text-tertiary);
  font-size: 0.875rem;
}

.rebuild-char-count {
  font-size: 0.75rem;
  font-family: var(--font-mono);
  text-align: right;
  margin: 0;
}

/* Suggestions */
.rebuild-suggestions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rebuild-suggestions-label {
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  margin: 0;
}

.rebuild-suggestions-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.rebuild-suggestion-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  background: var(--color-bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  font-size: 0.75rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
  text-align: left;
}

.rebuild-suggestion-chip:hover {
  background: var(--color-accent-subtle);
  border-color: var(--border-accent);
  color: var(--text-primary);
}

/* Original ref */
.rebuild-original-ref {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  overflow: hidden;
}

.rebuild-original-ref summary {
  padding: 8px 12px;
  font-size: 0.8125rem;
  color: var(--text-tertiary);
  cursor: pointer;
  list-style: none;
  user-select: none;
}

.rebuild-original-ref summary:hover { color: var(--text-secondary); }

.rebuild-original-ref p {
  padding: 0 12px 10px;
  font-size: 0.8125rem;
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0;
}

/* Footer */
.rebuild-modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px;
  border-top: 1px solid var(--border-subtle);
  background: var(--color-bg-surface);
}
`;
