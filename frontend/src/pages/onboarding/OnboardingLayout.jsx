import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Link } from 'react-router-dom';
import { Zap, Check } from 'lucide-react';

const STEPS = [
  { path: '/onboarding/upload',   label: 'Upload',   num: 1 },
  { path: '/onboarding/schema',   label: 'Schema',   num: 2 },
  { path: '/onboarding/confirm',  label: 'Confirm',  num: 3 },
  { path: '/onboarding/training', label: 'Training', num: 4 },
  { path: '/onboarding/integrate',label: 'Integrate',num: 5 },
];

export default function OnboardingLayout() {
  const location = useLocation();
  const current  = STEPS.findIndex(s => location.pathname === s.path);

  return (
    <div style={{ minHeight:'100vh', display:'flex', flexDirection:'column' }}>
      {/* Top bar */}
      <header style={{ borderBottom:'1px solid var(--border)', padding:'0 24px', height:64, display:'flex', alignItems:'center', justifyContent:'space-between', background:'var(--bg-surface)' }}>
        <Link to="/" style={{ display:'flex', alignItems:'center', gap:10 }}>
          <div style={{ width:32,height:32,borderRadius:9,background:'linear-gradient(135deg,#3b82f6,#818cf8)',display:'flex',alignItems:'center',justifyContent:'center' }}>
            <Zap size={15} color="#fff"/>
          </div>
          <span style={{ fontFamily:'Outfit',fontWeight:700,fontSize:18 }}>AI<span className="gradient-text">_POD</span></span>
        </Link>

        {/* Step progress */}
        <div style={{ display:'flex', alignItems:'center', gap:0 }}>
          {STEPS.map((step, i) => {
            const done   = i < current;
            const active = i === current;
            return (
              <div key={step.path} style={{ display:'flex', alignItems:'center' }}>
                <div style={{
                  display:'flex', alignItems:'center', gap:7,
                  color: done ? 'var(--success)' : active ? 'var(--accent-1)' : 'var(--text-muted)',
                  fontSize:13, fontWeight: active ? 600 : 400,
                }}>
                  <div style={{
                    width:28, height:28, borderRadius:'50%', display:'flex', alignItems:'center', justifyContent:'center',
                    background: done ? 'rgba(16,185,129,.15)' : active ? 'rgba(59,130,246,.15)' : 'transparent',
                    border: `2px solid ${done ? 'var(--success)' : active ? 'var(--accent-1)' : 'var(--border)'}`,
                    fontSize:12, fontWeight:600,
                    transition:'all .3s',
                  }}>
                    {done ? <Check size={13}/> : step.num}
                  </div>
                  <span style={{ display: window.innerWidth < 640 ? 'none' : 'block' }}>{step.label}</span>
                </div>
                {i < STEPS.length - 1 && (
                  <div style={{ width:32, height:1, background: done ? 'var(--success)' : 'var(--border)', margin:'0 6px', transition:'all .3s' }} />
                )}
              </div>
            );
          })}
        </div>

        <div style={{ fontSize:13, color:'var(--text-muted)' }}>
          Step {current + 1} of {STEPS.length}
        </div>
      </header>

      {/* Content */}
      <main style={{ flex:1, padding:'48px 24px', position:'relative', overflow:'hidden' }}>
        <div className="orb orb-blue"   style={{ width:400, height:400, top:-150, right:-100,  opacity:.3 }} />
        <div className="orb orb-purple" style={{ width:350, height:350, bottom:-100, left:-80, opacity:.25 }} />
        <div style={{ position:'relative', zIndex:1 }}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
