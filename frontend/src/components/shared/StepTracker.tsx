import { CheckCircle, Circle, AlertCircle, Loader } from 'lucide-react';
import type { ProgressStep } from '../../hooks/useBuildProgress';
import './StepTracker.css';

const STEP_NAMES: Record<number, string> = {
  1: 'Intent Analyzer',
  2: 'Planner',
  3: 'Architect',
  4: 'Backend Dev',
  5: 'Frontend Dev',
  6: 'Debugger',
  7: 'Code Review',
  8: 'Test Runner',
  9: 'Packager',
};

interface StepTrackerProps {
  steps: ProgressStep[];
  totalSteps?: number;
}

function StepIcon({ status }: { status: string }) {
  if (status === 'done')    return <CheckCircle size={18} className="step-icon step-icon--done" />;
  if (status === 'failed')  return <AlertCircle size={18} className="step-icon step-icon--failed" />;
  if (status === 'running') return <Loader size={18} className="step-icon step-icon--running spin-icon" />;
  return <Circle size={18} className="step-icon step-icon--pending" />;
}

export function StepTracker({ steps, totalSteps = 9 }: StepTrackerProps) {
  const stepsMap = new Map(steps.map(s => [s.step, s]));
  const completedCount = steps.filter(s => s.status === 'done').length;
  const progressPct = Math.round((completedCount / totalSteps) * 100);

  return (
    <div className="step-tracker">
      {/* Progress bar header */}
      <div className="step-tracker-header">
        <span className="step-tracker-label">{completedCount} of {totalSteps} steps</span>
        <span className="step-tracker-pct">{progressPct}%</span>
      </div>
      <div className="step-tracker-bar">
        <div
          className="step-tracker-bar-fill"
          style={{ width: `${progressPct}%` }}
          role="progressbar"
          aria-valuenow={progressPct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>

      {/* Steps list */}
      <div className="step-list">
        {Array.from({ length: totalSteps }, (_, i) => i + 1).map((stepNum) => {
          const step = stepsMap.get(stepNum);
          const status = step?.status ?? 'pending';
          const name = step?.step_name ?? STEP_NAMES[stepNum] ?? `Step ${stepNum}`;

          return (
            <div key={stepNum} className={`step-row step-row--${status}`}>
              <div className="step-connector">
                <StepIcon status={status} />
                {stepNum < totalSteps && (
                  <div className={`step-line${status === 'done' ? ' step-line--filled' : ''}`} />
                )}
              </div>

              <div className="step-body">
                <div className="step-meta">
                  <span className="step-num">Step {stepNum}</span>
                  <span className="step-name">{name}</span>
                  {status !== 'pending' && (
                    <span className={`step-status step-status--${status}`}>{status}</span>
                  )}
                </div>
                {step?.data?.message && (
                  <p className="step-message">{step.data.message}</p>
                )}
                {step?.timestamp && (
                  <span className="step-time">
                    {new Date(step.timestamp).toLocaleTimeString()}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
