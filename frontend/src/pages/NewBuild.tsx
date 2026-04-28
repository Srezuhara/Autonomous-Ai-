import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sparkles, Send, X, Lightbulb, Code2, Globe, Terminal, Database } from 'lucide-react';
import { api } from '../api/client';
import './NewBuild.css';

const EXAMPLE_PROMPTS = [
  { icon: <Globe size={16} />, label: 'Web App', text: 'A React task manager app with drag-and-drop boards, due dates, and local storage persistence.' },
  { icon: <Terminal size={16} />, label: 'CLI Tool', text: 'A Python CLI tool that renames files in bulk using regex patterns with a dry-run preview mode.' },
  { icon: <Code2 size={16} />, label: 'API', text: 'A FastAPI REST service for a URL shortener with SQLite storage, analytics, and custom slugs.' },
  { icon: <Database size={16} />, label: 'Data Script', text: 'A Python script that fetches stock prices from Yahoo Finance and generates a CSV report with charts.' },
];

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
    } catch (err: any) {
      setError(err?.message || 'Failed to start build. Is the backend running?');
      setIsSubmitting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      handleSubmit();
    }
  };

  const applyExample = (text: string) => {
    setPrompt(text);
    textareaRef.current?.focus();
  };

  return (
    <div className="new-build-container animate-fade-in">
      <div className="new-build-header">
        <div className="nb-badge">
          <Sparkles size={14} /> AI App Builder
        </div>
        <h1>Describe your application</h1>
        <p className="page-subtitle">
          The 9-agent pipeline will architect, code, review, and test your app autonomously.
        </p>
      </div>

      {/* Prompt Area */}
      <div className={`prompt-card glass-panel ${isOverLimit ? 'over-limit' : ''}`}>
        <textarea
          ref={textareaRef}
          className="prompt-textarea"
          placeholder="e.g. A Python FastAPI backend for a blog platform with user auth, posts, comments and a SQLite database..."
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={8}
          maxLength={MAX_CHARS + 50}
          disabled={isSubmitting}
          id="build-prompt-input"
        />
        <div className="prompt-footer">
          <span className={`char-count ${charsLeft < 100 ? 'warn' : ''} ${isOverLimit ? 'error' : ''}`}>
            {charsLeft < 0 ? `${Math.abs(charsLeft)} over limit` : `${charsLeft} chars left`}
          </span>
          <div className="prompt-actions">
            {prompt && (
              <button className="btn-secondary icon-btn" onClick={() => setPrompt('')} title="Clear">
                <X size={16} />
              </button>
            )}
            <button
              className="btn-primary submit-btn"
              onClick={handleSubmit}
              disabled={!canSubmit}
              id="start-build-btn"
            >
              {isSubmitting ? (
                <span className="submitting-inner">
                  <span className="spinner" />
                  Launching agents…
                </span>
              ) : (
                <><Send size={16} /> Build App</>
              )}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="error-banner glass-panel">
          <X size={16} className="text-error" />
          <span>{error}</span>
        </div>
      )}

      <div className="hint-row">
        <span><strong>Tip:</strong> Press <kbd>Ctrl</kbd>+<kbd>Enter</kbd> to submit</span>
      </div>

      {/* Example Prompts */}
      <div className="examples-section">
        <div className="examples-heading">
          <Lightbulb size={16} className="text-warning" />
          <span>Example prompts</span>
        </div>
        <div className="examples-grid">
          {EXAMPLE_PROMPTS.map((ex) => (
            <button key={ex.label} className="example-card glass-panel" onClick={() => applyExample(ex.text)}>
              <div className="example-label">
                {ex.icon}
                <span>{ex.label}</span>
              </div>
              <p>{ex.text}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
