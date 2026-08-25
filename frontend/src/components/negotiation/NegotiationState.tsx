import { Check } from 'lucide-react';
import './NegotiationState.css';

interface NegotiationStateProps {
  decision: string;
}

export default function NegotiationState({ decision }: NegotiationStateProps) {
  const states = [
    { label: 'DISCOVERED', key: 'discovered' },
    { label: 'OFFER CREATED', key: 'offer_created' },
    { label: 'COUNTER OFFER', key: 'counter_offer' },
    { label: 'POLICY CHECK', key: 'policy_check' },
    { label: 'APPROVED', key: 'approved' },
    { label: 'READY FOR PAYMENT', key: 'ready_payment' }
  ];

  // For the demo flow, the state has resolved to the final step (ready for payment / approved)
  const activeIndex = decision === 'APPROVED' ? 5 : 4; // if approved, index is READY FOR PAYMENT (5)

  return (
    <div className="state-tracker-card animate-fade-in">
      <div className="state-steps-wrapper">
        {states.map((state, idx) => {
          const isCompleted = idx < activeIndex;
          const isActive = idx === activeIndex;
          const isPending = idx > activeIndex;

          let stepClass = 'state-step';
          if (isCompleted) stepClass += ' state-completed';
          if (isActive) stepClass += ' state-active';
          if (isPending) stepClass += ' state-pending';

          return (
            <div key={state.key} className={stepClass}>
              <div className="step-circle">
                {isCompleted ? (
                  <Check className="step-check-icon" />
                ) : (
                  <span>{idx + 1}</span>
                )}
              </div>
              <span className="step-label">{state.label}</span>
              {idx < states.length - 1 && <div className="step-line" />}
            </div>
          );
        })}
      </div>
    </div>
  );
}
