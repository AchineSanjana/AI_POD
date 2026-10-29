import { useState } from 'react';
import { Copy, Check } from 'lucide-react';

export default function CodeBlock({ code, language = '' }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="code-block">
      {language && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, fontFamily: 'monospace' }}>
          {language}
        </div>
      )}
      <pre>{code}</pre>
      <button className="code-copy-btn" onClick={handleCopy} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        {copied ? <><Check size={12}/> Copied!</> : <><Copy size={12}/> Copy</>}
      </button>
    </div>
  );
}
