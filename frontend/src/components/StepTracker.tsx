import { CheckCircle, Circle, AlertCircle, Loader } from 'lucide-react';
import type { ProgressStep } from '../hooks/useBuildProgress';
import './StepTracker.css';

const STEP_NAMES: Record<number, string> = {
  1: 'Intent Analyzer',
  2: 'Planner',
  3: 'Frontend Developer',
  4: 'Backend Developer',
  5: 'Integration',
  6: 'Reviewer',
  7: 'Debugger',
  8: 'Tester',
  9: 'Packager',
};

interface StepTrackerProps {
  steps: ProgressStep[];
  totalSteps?: number;
}

function StepIcon({ status }: { status: string }) {
  if (status === 'done') return <CheckCircle size={20} className="step-icon done" />;
  if (status === 'failed') return <AlertCircle size={20} className="step-icon failed" />;
  if (status === 'running') return <Loader size={20} className="step-icon running spin-icon" />;
  return <Circle size={20} className="step-icon pending" />;
}

export default function StepTracker({ steps, totalSteps = 9 }: StepTrackerProps) {
  const stepsMap = new Map(steps.map(s => [s.step, s]));
  const completedCount = steps.filter(s => s.status === 'done').length;
  const progressPct = Math.round((completedCount / totalSteps) * 100);

  return (
    <div className="step-tracker">
      {/* Overall Progress */}
      <div className="tracker-progress-bar">
        <div className="tracker-progress-fill" style={{ width: `${progressPct}%` }} />
      </div>
      <p className="tracker-progress-label">{completedCount} / {totalSteps} steps complete</p>

      {/* Steps */}
      <div className="step-list">
        {Array.from({ length: totalSteps }, (_, i) => i + 1).map((stepNum) => {
          const step = stepsMap.get(stepNum);
          const status = step?.status ?? 'pending';
          const name = step?.step_name ?? STEP_NAMES[stepNum] ?? `Step ${stepNum}`;

          return (
            <div key={stepNum} className={`step-row ${status}`}>
              <div className="step-connector-wrap">
                <StepIcon status={status} />
                {stepNum < totalSteps && <div className={`step-line ${status === 'done' ? 'filled' : ''}`} />}
              </div>
              <div className="step-content">
                <div className="step-name-row">
                  <span className="step-num">Step {stepNum}</span>
                  <span className="step-name">{name}</span>
                  <span className={`step-status-label ${status}`}>{status}</span>
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
