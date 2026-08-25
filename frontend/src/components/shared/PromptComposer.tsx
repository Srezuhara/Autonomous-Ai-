import { forwardRef, type ReactNode } from 'react';
import { CornerDownLeft } from 'lucide-react';
import { promptState } from '../../lib/prompt';
import './PromptComposer.css';

/**
 * PromptComposer — the one prompt field in the product.
 *
 * NewBuild and RebuildModal both take free text that goes to the same endpoint
 * under the same 2000-character contract, but each had built its own: the
 * composer had a budget meter and a readout, the modal had a bare textarea and
 * a countdown from a limit (500) that no longer matches the API. They are now
 * the same control, so a change to the contract lands in both.
 *
 * Label, field, meter and footer share a single surface with no inner boxes —
 * the meter is flush to the footer rule so the whole thing reads as one
 * instrument rather than a box with a bar in it.
 */
interface PromptComposerProps {
  id:            string;
  label:         string;
  value:         string;
  onChange:      (value: string) => void;
  onSubmit?:     () => void;
  placeholder?:  string;
  /** Shown in the readout while the field is untouched. */
  idleText?:     string;
  disabled?:     boolean;
  /** Minimum field height in px — the modal is shorter than the full page. */
  minHeight?:    number;
  /** Buttons for the footer's trailing edge. */
  actions?:      ReactNode;
  className?:    string;
}

export const PromptComposer = forwardRef<HTMLTextAreaElement, PromptComposerProps>(
  function PromptComposer({
    id, label, value, onChange, onSubmit, placeholder, idleText,
    disabled, minHeight, actions, className = '',
  }, ref) {
    const { isOverLimit, usedPct, readout } = promptState(value, idleText);
    const readoutId = `${id}-readout`;

    const handleKeyDown = (e: React.KeyboardEvent) => {
      if (onSubmit && (e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        onSubmit();
      }
    };

    return (
      <div className={`composer${isOverLimit ? ' composer--over' : ''} ${className}`.trim()}>
        <label htmlFor={id} className="ulabel composer__label">{label}</label>

        <textarea
          ref={ref}
          id={id}
          className="composer__input"
          style={minHeight ? { minHeight } : undefined}
          placeholder={placeholder}
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          aria-describedby={readoutId}
          aria-invalid={isOverLimit || undefined}
        />

        {/* Budget meter — deliberately 2px and almost unlit until the prompt is
            long: at 40 characters of a 2000 budget there is nothing to report. */}
        <div className="composer__meter" aria-hidden>
          <div className="composer__meter-fill" style={{ width: `${usedPct}%` }} />
        </div>

        <footer className="composer__footer">
          <span
            id={readoutId}
            className={`composer__readout composer__readout--${readout.tone}`}
            aria-live="polite"
          >
            {readout.text}
          </span>

          <div className="composer__actions">
            {onSubmit && (
              <span className="composer__shortcut" aria-hidden>
                <kbd className="keycap">Ctrl</kbd>
                <kbd className="keycap"><CornerDownLeft size={9} /></kbd>
              </span>
            )}
            {actions}
          </div>
        </footer>
      </div>
    );
  }
);
