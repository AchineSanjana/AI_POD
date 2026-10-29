import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { login as apiLogin, loginMfa, getMe } from '../api/client';
import { Zap, Mail, Lock, Eye, EyeOff, ArrowRight, ShieldCheck } from 'lucide-react';

export default function SignIn() {
  const navigate = useNavigate();
  const { login: authLogin } = useAuth();

  const [form,  setForm]  = useState({ email:'', password:'', mfa_code:'' });
  const [showPw,setShowPw]= useState(false);
  const [error, setError] = useState('');
  const [loading,setLoading]=useState(false);
  const [mfaTicket,setMfaTicket]=useState(null);

  const handleChange = e => setForm(f=>({...f,[e.target.name]:e.target.value}));

  const handleLogin = async (e) => {
    e.preventDefault(); setError(''); setLoading(true);
    try {
      const data = await apiLogin({ email: form.email, password: form.password });
      if (data.mfa_required && data.mfa_ticket) {
        setMfaTicket(data.mfa_ticket);
        setLoading(false); return;
      }
      const token = data.access_token || data.session_token;
      const me = await getMe();
      authLogin(token, me);
      navigate('/dashboard');
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally { setLoading(false); }
  };

  const handleMfa = async (e) => {
    e.preventDefault(); setError(''); setLoading(true);
    try {
      const data = await loginMfa({ mfa_ticket: mfaTicket, code: form.mfa_code });
      const token = data.access_token || data.session_token;
      const me = await getMe();
      authLogin(token, me);
      navigate('/dashboard');
    } catch (err) {
      setError(err.message || '2FA verification failed');
    } finally { setLoading(false); }
  };

  return (
    <div style={{ minHeight:'100vh', display:'flex', alignItems:'center', justifyContent:'center', padding:'100px 24px 40px', position:'relative', overflow:'hidden' }}>
      <div className="orb orb-blue"   style={{ width:400, height:400, top:-80,  right:-80,  opacity:.5 }} />
      <div className="orb orb-cyan"   style={{ width:300, height:300, bottom:-60, left:-60, opacity:.4 }} />

      <div style={{ width:'100%', maxWidth:440, position:'relative', zIndex:1 }}>
        {/* Logo */}
        <div style={{ textAlign:'center', marginBottom:40 }}>
          <Link to="/" style={{ display:'inline-flex', alignItems:'center', gap:10, marginBottom:8 }}>
            <div style={{ width:44,height:44,borderRadius:12,background:'linear-gradient(135deg,#3b82f6,#818cf8)',display:'flex',alignItems:'center',justifyContent:'center',boxShadow:'0 4px 20px rgba(59,130,246,.4)' }}>
              <Zap size={22} color="#fff" />
            </div>
            <span style={{ fontFamily:'Outfit',fontWeight:800,fontSize:24 }}>AI<span className="gradient-text">_POD</span></span>
          </Link>
          <h2 style={{ marginBottom:8 }}>{mfaTicket ? 'Two-Factor Auth' : 'Welcome back'}</h2>
          <p style={{ fontSize:14 }}>{mfaTicket ? 'Enter your 6-digit TOTP code' : 'Sign in to your account'}</p>
        </div>

        <div className="card-glass" style={{ padding:32 }}>
          {error && <div className="alert alert-error mb-6">{error}</div>}

          {!mfaTicket ? (
            <form onSubmit={handleLogin} style={{ display:'flex', flexDirection:'column', gap:20 }}>
              <div className="form-group">
                <label className="form-label">Email</label>
                <div className="input-icon-wrap">
                  <Mail className="icon" />
                  <input name="email" type="email" value={form.email} onChange={handleChange} placeholder="you@company.com" required />
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">Password</label>
                <div className="input-icon-wrap">
                  <Lock className="icon" />
                  <input name="password" type={showPw?'text':'password'} value={form.password} onChange={handleChange} placeholder="Your password" required style={{ paddingRight:44 }} />
                  <button type="button" onClick={()=>setShowPw(s=>!s)} style={{ position:'absolute',right:12,top:'50%',transform:'translateY(-50%)',color:'var(--text-muted)' }}>
                    {showPw?<EyeOff size={16}/>:<Eye size={16}/>}
                  </button>
                </div>
              </div>
              <button type="submit" className="btn btn-primary w-full" disabled={loading} style={{ marginTop:4 }}>
                {loading ? 'Signing in…' : <><span>Sign In</span><ArrowRight size={16}/></>}
              </button>
            </form>
          ) : (
            <form onSubmit={handleMfa} style={{ display:'flex', flexDirection:'column', gap:20 }}>
              <div style={{ textAlign:'center', padding:'16px 0' }}>
                <div style={{ width:56,height:56,borderRadius:16,background:'rgba(59,130,246,.15)',border:'1px solid rgba(59,130,246,.3)',display:'flex',alignItems:'center',justifyContent:'center',margin:'0 auto 12px' }}>
                  <ShieldCheck size={28} color="#3b82f6"/>
                </div>
                <p style={{ fontSize:14 }}>Open your authenticator app and enter the 6-digit code.</p>
              </div>
              <div className="form-group">
                <label className="form-label">Authentication Code</label>
                <input name="mfa_code" value={form.mfa_code} onChange={handleChange} placeholder="000 000" maxLength={6} required style={{ textAlign:'center', fontSize:24, letterSpacing:8, fontFamily:'monospace' }} />
              </div>
              <button type="submit" className="btn btn-primary w-full" disabled={loading}>
                {loading ? 'Verifying…' : 'Verify & Sign In'}
              </button>
              <button type="button" onClick={()=>setMfaTicket(null)} className="btn btn-ghost w-full" style={{ textAlign:'center' }}>← Back to Login</button>
            </form>
          )}

          {!mfaTicket && (
            <>
              <div className="divider-text mt-6">don't have an account</div>
              <Link to="/signup" className="btn btn-secondary w-full" style={{ display:'flex', justifyContent:'center' }}>Create Account</Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
