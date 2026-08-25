import React, { useState } from 'react';
import { Search, CornerDownLeft } from 'lucide-react';
import './IntentInput.css';

interface IntentInputProps {
  onSubmit: (intent: string) => void;
  disabled: boolean;
}

export default function IntentInput({ onSubmit, disabled }: IntentInputProps) {
  const [intent, setIntent] = useState('');
  
  const examples = [
    "I need wireless earbuds under ₹2,000.",
    "SoundWave Wireless Earbuds with a charging case bundle."
  ];

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (intent.trim()) {
      onSubmit(intent.trim());
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (intent.trim() && !disabled) {
        onSubmit(intent.trim());
      }
    }
  };

  return (
    <div className="intent-input-container animate-fade-in">
      <form onSubmit={handleSubmit} className="intent-form">
        <div className="intent-textarea-wrapper">
          <textarea
            value={intent}
            onChange={(e) => setIntent(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="What are you looking for?"
            disabled={disabled}
            rows={3}
            className="intent-textarea"
          />
          <button 
            type="submit" 
            disabled={disabled || !intent.trim()} 
            className="intent-submit-btn"
            title="Press Enter or click to search"
          >
            <Search className="submit-icon" />
            <span className="submit-kbd">
              <CornerDownLeft className="kbd-icon" />
            </span>
          </button>
        </div>
      </form>

      <div className="intent-examples">
        <span className="examples-label">Try asking:</span>
        <div className="examples-list">
          {examples.map((ex, i) => (
            <button
              key={i}
              type="button"
              disabled={disabled}
              onClick={() => setIntent(ex)}
              className="example-chip"
            >
              "{ex}"
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
