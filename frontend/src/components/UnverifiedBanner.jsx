import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { AlertCircle, ArrowRight } from 'lucide-react';

export default function UnverifiedBanner() {
  const { user } = useAuth();

  if (!user || user.email_verified !== false) {
    return null;
  }

  return (
    <div
      role="alert"
      style={{
        background: 'rgba(245, 158, 11, 0.12)',
        border: '1px solid rgba(245, 158, 11, 0.35)',
        borderRadius: 'var(--radius-md, 10px)',
        padding: '12px 18px',
        marginBottom: 24,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        color: '#fbbf24',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14 }}>
        <AlertCircle size={18} style={{ flexShrink: 0, color: '#f59e0b' }} />
        <span>
          Your email{user.email ? <> (<strong>{user.email}</strong>)</> : ''} is not verified. Please verify your email to secure your account.
        </span>
      </div>

      <Link
        to="/verify-email"
        state={{ email: user.email }}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 13,
          fontWeight: 600,
          color: '#fff',
          background: 'linear-gradient(135deg, #f59e0b, #d97706)',
          boxShadow: '0 2px 10px rgba(245, 158, 11, 0.3)',
          padding: '6px 14px',
          borderRadius: 'var(--radius-sm, 6px)',
          textDecoration: 'none',
          whiteSpace: 'nowrap',
          transition: 'all .2s ease',
        }}
      >
        <span>Verify Email</span>
        <ArrowRight size={14} />
      </Link>
    </div>
  );
}

