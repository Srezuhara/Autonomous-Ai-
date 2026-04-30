import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sparkles, Send, X, Lightbulb, Globe, Terminal, Code2, Database } from 'lucide-react';
import { api } from '../api/client';
import './NewBuild.css';

const EXAMPLES = [
  { icon: Globe,    label: 'Web App',     text: 'A React task manager app with drag-and-drop boards, due dates, and local storage persistence.' },
  { icon: Terminal, label: 'CLI Tool',    text: 'A Python CLI tool that renames files in bulk using regex patterns with a dry-run preview mode.' },
  { icon: Code2,    label: 'REST API',    text: 'A FastAPI URL shortener with SQLite storage, analytics dashboard, and custom slug support.' },
  { icon: Database, label: 'Data Script', text: 'A Python script that fetches stock prices from Yahoo Finance and generates a CSV report with charts.' },
] as const;

const MAX_CHARS = 2000;

export default function NewBuild() {
  const [prompt, setPrompt] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const navigate = useNavigate();

  const charsLeft = MAX_CHARS - prompt.length;
  const isOverLimit = charsLeft < 0;
  const canSubmit = prompt.trim().length > 10 && !isOverLimit && !isSubmitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const res = await api.createProject(prompt.trim());
      navigate(`/build/${res.build_id}`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to start build. Is the backend running?';
      setError(message);
      setIsSubmitting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') handleSubmit();
  };

  return (
    <div className="new-build page-wrapper animate-in">
      {/* Header */}
      <div className="new-build-header">
        <div className="new-build-badge">
          <Sparkles size={13} />
          9-Agent AI Pipeline
        </div>
        <h1 className="new-build-title">Describe your application</h1>
        <p className="new-build-subtitle">
          The pipeline will architect, code, review, debug, and test your app autonomously.
        </p>
      </div>

      {/* Prompt Area */}
      <div className={`prompt-card card${isOverLimit ? ' prompt-card--over' : ''}`}>
        <textarea
          ref={textareaRef}
          className="prompt-textarea"
          placeholder="e.g. A FastAPI backend for a blog platform with user auth, posts, comments, and a SQLite database..."
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={7}
          disabled={isSubmitting}
          aria-label="App description prompt"
          id="build-prompt-input"
        />
        <div className="prompt-footer">
          <span className={`char-count${charsLeft < 100 ? ' char-count--warn' : ''}${isOverLimit ? ' char-count--error' : ''}`}>
            {isOverLimit ? `${Math.abs(charsLeft)} over limit` : `${charsLeft} chars left`}
          </span>
          <div className="prompt-actions">
            {prompt && (
              <button
                className="btn btn-ghost btn-icon"
                onClick={() => { setPrompt(''); textareaRef.current?.focus(); }}
                aria-label="Clear prompt"
              >
                <X size={15} />
              </button>
            )}
            <button
              className="btn btn-primary"
              onClick={handleSubmit}
              disabled={!canSubmit}
              id="start-build-btn"
            >
              {isSubmitting
                ? <><div className="spinner" /> Launching agents…</>
                : <><Send size={15} /> Build App</>
              }
            </button>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="new-build-error card" role="alert">
          <X size={15} style={{ color: 'var(--color-error)', flexShrink: 0 }} />
          <span>{error}</span>
        </div>
      )}

      <p className="new-build-hint">
        Press <kbd>Ctrl</kbd>+<kbd>Enter</kbd> to submit
      </p>

      {/* Examples */}
      <div className="examples-section">
        <div className="examples-heading">
          <Lightbulb size={14} style={{ color: 'var(--color-warning)' }} />
          <span>Example prompts</span>
        </div>
        <div className="examples-grid">
          {EXAMPLES.map(({ icon: Icon, label, text }) => (
            <button
              key={label}
              className="example-card card"
              onClick={() => { setPrompt(text); textareaRef.current?.focus(); }}
            >
              <div className="example-card-label">
                <Icon size={14} />
                <span>{label}</span>
              </div>
              <p className="example-card-text">{text}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
