import { useState, useEffect, useRef, useCallback } from 'react';
import { Link, useNavigate, useLocation, useSearchParams } from 'react-router-dom';
import { verifyEmail, resendVerification } from '../api/client';
import { Zap, Mail, ArrowRight, RefreshCw, CheckCircle2, AlertCircle } from 'lucide-react';

export default function VerifyEmail() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();

  // Read email from router state or query param
  const initialEmail = location.state?.email || searchParams.get('email') || '';
  const [email, setEmail] = useState(initialEmail);
  const [editingEmail, setEditingEmail] = useState(!initialEmail);

  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [resending, setResending] = useState(false);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState(
    location.state?.info || location.state?.message || ''
  );

  // 60-second cooldown timer for resend button
  const [cooldown, setCooldown] = useState(location.state?.autoResent ? 60 : 0);
  const autoResendTriggered = useRef(false);

  // Handle countdown
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => {
      setCooldown((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  const triggerResend = useCallback(async (targetEmail) => {
    const toSend = targetEmail || email;
    if (!toSend || cooldown > 0 || resending) return;

    setError('');
    setResending(true);
    try {
      await resendVerification({ email: toSend.trim() });
      setCooldown(60);
      setSuccessMsg('A new 6-digit verification code has been sent to your email.');
    } catch (err) {
      if (err?.status === 429) {
        setCooldown(60);
        setError(err.message || 'Rate limit exceeded. Please wait 60 seconds before requesting another code.');
      } else if (!err?.status) {
        setError('Network error. Could not connect to the server. Please check your internet connection.');
      } else {
        setError(err.message || 'Failed to resend verification code. Please try again.');
      }
    } finally {
      setResending(false);
    }
  }, [email, cooldown, resending]);

  // If instructed to autoResend on arrival and not already triggered
  useEffect(() => {
    if (location.state?.autoResend && !autoResendTriggered.current && email) {
      autoResendTriggered.current = true;
      triggerResend(email);
    }
  }, [location.state, email, triggerResend]);

  const handleCodeChange = (e) => {
    const digits = e.target.value.replace(/\D/g, '').slice(0, 6);
    setCode(digits);
    if (error) setError('');
  };

  const handlePaste = (e) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData('text') || '';
    const digits = pasted.replace(/\D/g, '').slice(0, 6);
    setCode(digits);
    if (error) setError('');
  };

  const handleVerify = async (e) => {
    e.preventDefault();
    if (!email) {
      setError('Please provide your email address.');
      setEditingEmail(true);
      return;
    }
    if (code.length !== 6) {
      setError('Please enter the full 6-digit verification code.');
      return;
    }

    setLoading(true);
    setError('');
    try {
      await verifyEmail({ email: email.trim(), code: code.trim() });
      setSuccessMsg('Email verified successfully! Redirecting to sign in...');
      setTimeout(() => {
        navigate('/signin', {
          state: {
            email: email.trim(),
            message: 'Email verified successfully. Please sign in to continue.',
          },
        });
      }, 1200);
    } catch (err) {
      if (err?.status === 400) {
        setError(err.message || 'Invalid or expired verification code. Please request a new one.');
      } else if (err?.status === 429) {
        setError(err.message || 'Too many attempts. Please wait a moment before trying again.');
      } else if (!err?.status) {
        setError('Network error. Unable to reach the server. Please try again.');
      } else {
        setError(err.message || 'Verification failed. Please check the code and try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '100px 24px 40px', position: 'relative', overflow: 'hidden' }}>
      {/* Background Orbs */}
      <div className="orb orb-blue" style={{ width: 400, height: 400, top: -100, right: -100, opacity: 0.5 }} />
      <div className="orb orb-purple" style={{ width: 350, height: 350, bottom: -80, left: -80, opacity: 0.4 }} />

      <div style={{ width: '100%', maxWidth: 460, position: 'relative', zIndex: 1 }}>
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 36 }}>
          <Link to="/" style={{ display: 'inline-flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <div style={{ width: 44, height: 44, borderRadius: 12, background: 'linear-gradient(135deg,#3b82f6,#818cf8)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 20px rgba(59,130,246,.4)' }}>
              <Zap size={22} color="#fff" />
            </div>
            <span style={{ fontFamily: 'Outfit', fontWeight: 800, fontSize: 24 }}>AI<span className="gradient-text">_POD</span></span>
          </Link>
          <h2 style={{ marginBottom: 8 }}>Verify your email</h2>
          <p style={{ fontSize: 14 }}>Enter the 6-digit code sent to your inbox to activate your account.</p>
        </div>

        {/* Card */}
        <div className="card-glass" style={{ padding: 32 }}>
          {/* Target Email display / edit */}
          {editingEmail ? (
            <div className="form-group mb-6">
              <label className="form-label">Email Address</label>
              <div className="input-icon-wrap">
                <Mail className="icon" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  required
                />
              </div>
              {email && (
                <button
                  type="button"
                  onClick={() => setEditingEmail(false)}
                  className="btn btn-ghost"
                  style={{ alignSelf: 'flex-start', padding: '4px 8px', fontSize: 12, marginTop: 4 }}
                >
                  Save & Continue
                </button>
              )}
            </div>
          ) : (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '10px 14px',
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm, 8px)',
              marginBottom: 20,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, overflow: 'hidden' }}>
                <Mail size={16} color="var(--accent-1)" style={{ flexShrink: 0 }} />
                <span style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-primary)', textOverflow: 'ellipsis', overflow: 'hidden' }}>
                  {email}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setEditingEmail(true)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--accent-1)',
                  cursor: 'pointer',
                  fontSize: 12,
                  fontWeight: 600,
                  padding: '2px 6px',
                }}
              >
                Change
              </button>
            </div>
          )}

          {/* Success banner */}
          {successMsg && (
            <div className="alert alert-success mb-6" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <CheckCircle2 size={16} style={{ flexShrink: 0 }} />
              <span>{successMsg}</span>
            </div>
          )}

          {/* Error banner */}
          {error && (
            <div className="alert alert-error mb-6" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <AlertCircle size={16} style={{ flexShrink: 0 }} />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleVerify} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <div className="form-group">
              <label className="form-label" style={{ textAlign: 'center' }}>
                6-Digit Verification Code
              </label>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                autoComplete="one-time-code"
                autoFocus
                value={code}
                onChange={handleCodeChange}
                onPaste={handlePaste}
                placeholder="000000"
                maxLength={6}
                required
                style={{
                  textAlign: 'center',
                  fontSize: 28,
                  letterSpacing: 10,
                  fontFamily: 'monospace',
                  padding: '12px 16px',
                }}
              />
              <span style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'center', marginTop: 4 }}>
                Enter or paste your 6-digit code
              </span>
            </div>

            <button
              type="submit"
              className="btn btn-primary w-full"
              disabled={loading || code.length !== 6 || !email}
              style={{ marginTop: 4 }}
            >
              {loading ? 'Verifying…' : (
                <>
                  <span>Verify Email</span>
                  <ArrowRight size={16} />
                </>
              )}
            </button>
          </form>

          {/* Resend button with cooldown */}
          <div style={{ marginTop: 20, textAlign: 'center' }}>
            <button
              type="button"
              onClick={() => triggerResend(email)}
              disabled={resending || cooldown > 0 || !email}
              className="btn btn-ghost w-full"
              style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
            >
              <RefreshCw size={14} className={resending ? 'spin' : ''} />
              <span>
                {resending
                  ? 'Sending code…'
                  : cooldown > 0
                  ? `Resend code in ${cooldown}s`
                  : 'Resend verification code'}
              </span>
            </button>
          </div>

          <div className="divider-text mt-6">or</div>

          <Link
            to="/signin"
            state={{ email }}
            className="btn btn-secondary w-full"
            style={{ display: 'flex', justifyContent: 'center' }}
          >
            Back to Sign In
          </Link>
        </div>

        <p style={{ textAlign: 'center', fontSize: 12, color: 'var(--text-muted)', marginTop: 24 }}>
          Didn't receive the email? Check your spam folder or click Resend above.
        </p>
      </div>
    </div>
  );
}
