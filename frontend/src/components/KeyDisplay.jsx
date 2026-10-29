import { useState } from 'react';
import { Eye, EyeOff, Copy, Check } from 'lucide-react';

export default function KeyDisplay({ label, value, secret = false }) {
  const [revealed, setRevealed] = useState(!secret);
  const [copied,   setCopied]   = useState(false);

  const display = revealed ? value : value.slice(0, 10) + '•'.repeat(Math.max(0, value.length - 10));

  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{
      background: 'var(--bg-input)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius-sm)',
      padding: '10px 14px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        {label && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>{label}</div>}
        <code style={{ fontSize: 13, color: 'var(--text-primary)', fontFamily: 'monospace', wordBreak: 'break-all' }}>
          {display}
        </code>
      </div>
      <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
        {secret && (
          <button onClick={() => setRevealed(r => !r)} style={{ color: 'var(--text-muted)', padding: 4, borderRadius: 4, transition: 'color .2s' }}
            title={revealed ? 'Hide' : 'Reveal'}>
            {revealed ? <EyeOff size={15}/> : <Eye size={15}/>}
          </button>
        )}
        <button onClick={handleCopy} style={{ color: copied ? 'var(--success)' : 'var(--text-muted)', padding: 4, borderRadius: 4, transition: 'color .2s' }}>
          {copied ? <Check size={15}/> : <Copy size={15}/>}
        </button>
      </div>
    </div>
  );
}
