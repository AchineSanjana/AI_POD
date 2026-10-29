import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { signup } from '../api/client';
import { Zap, Building2, Mail, Lock, Eye, EyeOff, ArrowRight, CheckCircle2 } from 'lucide-react';

const INDUSTRIES = ['E-Commerce','Grocery','Fashion','Telecom','SaaS','Other'];

function slugify(str) {
  return str.toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/g,'').slice(0,32);
}

function pwStrength(pw) {
  let score = 0;
  if (pw.length >= 8)  score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  return score;
}

export default function SignUp() {
  const navigate = useNavigate();
  const { login: authLogin } = useAuth();

  const [form, setForm] = useState({ company_name:'', email:'', password:'', confirm:'', industry:'' });
  const [showPw, setShowPw] = useState(false);
  const [error, setError]   = useState('');
  const [loading, setLoading] = useState(false);

  const tenantPreview = slugify(form.company_name);
  const strength      = pwStrength(form.password);
  const strengthLabel = ['','Weak','Fair','Good','Strong'][strength];
  const strengthColor = ['','#ef4444','#f59e0b','#3b82f6','#10b981'][strength];

  const handleChange = e => setForm(f => ({ ...f, [e.target.name]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (form.password !== form.confirm) { setError('Passwords do not match'); return; }
    if (form.password.length < 8) { setError('Password must be at least 8 characters'); return; }
    setLoading(true);
    try {
      const data = await signup({ company_name: form.company_name, email: form.email, password: form.password });
      // Store keys
      localStorage.setItem('aipod_sk', data.private_key);
      localStorage.setItem('aipod_pk', data.public_key);
      authLogin(data.private_key, { company_name: data.company_name, tenant_id: data.tenant_id, public_key: data.public_key, email_verified: data.email_verified });
      navigate('/onboarding/upload');
    } catch (err) {
      setError(err.message || 'Signup failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '100px 24px 40px', position: 'relative', overflow: 'hidden' }}>
      {/* Orbs */}
      <div className="orb orb-blue"   style={{ width: 400, height: 400, top: -100, right: -100, opacity: .5 }} />
      <div className="orb orb-purple" style={{ width: 350, height: 350, bottom: -80, left: -80,  opacity: .4 }} />

      <div style={{ width: '100%', maxWidth: 480, position: 'relative', zIndex: 1 }}>
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <Link to="/" style={{ display: 'inline-flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <div style={{ width: 44, height: 44, borderRadius: 12, background: 'linear-gradient(135deg,#3b82f6,#818cf8)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 20px rgba(59,130,246,.4)' }}>
              <Zap size={22} color="#fff" />
            </div>
            <span style={{ fontFamily:'Outfit', fontWeight:800, fontSize:24 }}>AI<span className="gradient-text">_POD</span></span>
          </Link>
          <h2 style={{ marginBottom: 8 }}>Create your account</h2>
          <p style={{ fontSize: 14 }}>Start recommending in minutes — no ML expertise needed.</p>
        </div>

        {/* Card */}
        <div className="card-glass" style={{ padding: 32 }}>
          {error && (
            <div className="alert alert-error mb-6">{error}</div>
          )}

          <form onSubmit={handleSubmit} style={{ display:'flex', flexDirection:'column', gap:20 }}>
            {/* Company name */}
            <div className="form-group">
              <label className="form-label">Company Name</label>
              <div className="input-icon-wrap">
                <Building2 className="icon" />
                <input name="company_name" value={form.company_name} onChange={handleChange} placeholder="Acme Corp" required />
              </div>
              {form.company_name && (
                <div style={{ fontSize:12, color:'var(--text-muted)', display:'flex', alignItems:'center', gap:6 }}>
                  <span>Tenant ID:</span>
                  <code style={{ color:'var(--accent-3)', background:'rgba(6,182,212,.1)', padding:'1px 6px', borderRadius:4 }}>{tenantPreview}</code>
                </div>
              )}
            </div>

            {/* Email */}
            <div className="form-group">
              <label className="form-label">Work Email</label>
              <div className="input-icon-wrap">
                <Mail className="icon" />
                <input name="email" type="email" value={form.email} onChange={handleChange} placeholder="you@company.com" required />
              </div>
            </div>

            {/* Industry */}
            <div className="form-group">
              <label className="form-label">Industry <span style={{color:'var(--text-muted)'}}>(optional)</span></label>
              <select name="industry" value={form.industry} onChange={handleChange}>
                <option value="">Select your industry</option>
                {INDUSTRIES.map(i => <option key={i} value={i}>{i}</option>)}
              </select>
            </div>

            {/* Password */}
            <div className="form-group">
              <label className="form-label">Password</label>
              <div className="input-icon-wrap">
                <Lock className="icon" />
                <input name="password" type={showPw ? 'text' : 'password'} value={form.password} onChange={handleChange} placeholder="Min 8 characters" required style={{ paddingRight: 44 }} />
                <button type="button" onClick={() => setShowPw(s=>!s)} style={{ position:'absolute', right:12, top:'50%', transform:'translateY(-50%)', color:'var(--text-muted)' }}>
                  {showPw ? <EyeOff size={16}/> : <Eye size={16}/>}
                </button>
              </div>
              {form.password && (
                <div style={{ display:'flex', alignItems:'center', gap:8, marginTop:4 }}>
                  <div style={{ flex:1, height:3, borderRadius:99, background:'var(--bg-input)', overflow:'hidden' }}>
                    <div style={{ width:`${(strength/4)*100}%`, height:'100%', background:strengthColor, transition:'all .3s', borderRadius:99 }} />
                  </div>
                  <span style={{ fontSize:11, color:strengthColor, fontWeight:600 }}>{strengthLabel}</span>
                </div>
              )}
            </div>

            {/* Confirm */}
            <div className="form-group">
              <label className="form-label">Confirm Password</label>
              <div className="input-icon-wrap">
                <Lock className="icon" />
                <input name="confirm" type="password" value={form.confirm} onChange={handleChange} placeholder="Repeat password" required />
              </div>
              {form.confirm && form.password === form.confirm && (
                <div style={{ fontSize:12, color:'var(--success)', display:'flex', alignItems:'center', gap:4, marginTop:2 }}>
                  <CheckCircle2 size={12}/> Passwords match
                </div>
              )}
            </div>

            <button type="submit" className="btn btn-primary w-full" disabled={loading} style={{ marginTop: 4 }}>
              {loading ? 'Creating Account…' : <><span>Create Account</span><ArrowRight size={16}/></>}
            </button>
          </form>

          <div className="divider-text mt-6">already have an account</div>

          <Link to="/signin" className="btn btn-secondary w-full" style={{ display:'flex', justifyContent:'center' }}>
            Sign In
          </Link>
        </div>

        <p style={{ textAlign:'center', fontSize:12, color:'var(--text-muted)', marginTop:24 }}>
          Your private key is shown once after signup. Store it securely.
        </p>
      </div>
    </div>
  );
}
