import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { onboardStatus, getMe } from '../../api/client';
import { Brain, Key, BarChart3, Zap, ArrowRight, RefreshCw, CheckCircle2, AlertCircle } from 'lucide-react';

function StatCard({ label, value, sub, color, icon: Icon }) {
  return (
    <div className="card" style={{ display:'flex', flexDirection:'column', gap:16 }}>
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
        <span style={{ fontSize:13, color:'var(--text-secondary)' }}>{label}</span>
        <div style={{ width:36,height:36,borderRadius:10,background:`${color}18`,border:`1px solid ${color}30`,display:'flex',alignItems:'center',justifyContent:'center' }}>
          <Icon size={16} color={color}/>
        </div>
      </div>
      <div>
        <div style={{ fontFamily:'Outfit',fontWeight:700,fontSize:'1.8rem' }}>{value}</div>
        {sub && <div style={{ fontSize:12,color:'var(--text-muted)',marginTop:4 }}>{sub}</div>}
      </div>
    </div>
  );
}

const RECENT_EVENTS = [
  { id:1, customer:'7590-VHVEG', event:'view',     product:'OnlineSecurity', time:'2 min ago' },
  { id:2, customer:'2345-ABCD',  event:'purchase', product:'TechSupport',    time:'5 min ago' },
  { id:3, customer:'9012-XYZ',   event:'click',    product:'StreamingTV',    time:'8 min ago' },
  { id:4, customer:'1111-EFGH',  event:'add_to_cart',product:'OnlineSecurity',time:'12 min ago'},
  { id:5, customer:'5678-IJKL',  event:'view',     product:'DeviceProtect',  time:'18 min ago'},
];

const EVENT_COLOR = { view:'#3b82f6', click:'#818cf8', add_to_cart:'#f59e0b', purchase:'#10b981' };

export default function Overview() {
  const { user, setUser } = useAuth();
  const [modelInfo, setModelInfo] = useState(null);
  const [loading,   setLoading]   = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [me, status] = await Promise.allSettled([getMe(), onboardStatus()]);
        if (me.status === 'fulfilled') setUser(me.value);
        if (status.status === 'fulfilled') setModelInfo(status.value);
      } catch {}
      setLoading(false);
    };
    load();
  }, []);

  const quickActions = [
    { to:'/onboarding/upload', label:'Upload New Dataset', icon:Zap,      color:'#3b82f6' },
    { to:'/dashboard/keys',    label:'View API Keys',       icon:Key,      color:'#818cf8' },
    { to:'/dashboard/model',   label:'Re-train Model',      icon:Brain,    color:'#10b981' },
    { to:'/dashboard/analytics',label:'View Analytics',     icon:BarChart3,color:'#06b6d4' },
  ];

  return (
    <div>
      {/* Header */}
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:32 }}>
        <div>
          <h3 style={{ marginBottom:4 }}>Welcome back{user?.company_name ? `, ${user.company_name}` : ''} 👋</h3>
          <p style={{ fontSize:14 }}>Here's what's happening with your recommendation engine.</p>
        </div>
        {!user?.email_verified && (
          <div className="badge badge-yellow"><AlertCircle size={12}/> Email not verified</div>
        )}
        {user?.email_verified && (
          <div className="badge badge-green"><CheckCircle2 size={12}/> Verified</div>
        )}
      </div>

      {/* Stats */}
      <div className="grid-4 mb-8">
        <StatCard label="Model Status"     value={loading ? '…' : modelInfo?.status || 'Ready'} sub="Current state" color="#10b981" icon={Brain}/>
        <StatCard label="Tenant ID"        value={user?.tenant_id || '—'} sub="Your identifier" color="#3b82f6" icon={Zap}/>
        <StatCard label="Requests Today"   value="1,240" sub="+12% from yesterday" color="#818cf8" icon={BarChart3}/>
        <StatCard label="API Keys Active"  value="2" sub="pk + sk" color="#06b6d4" icon={Key}/>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:24 }}>
        {/* Model Health */}
        <div className="card">
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:20 }}>
            <h4>Model Health</h4>
            <Link to="/dashboard/model" style={{ fontSize:13, color:'var(--accent-1)', display:'flex', alignItems:'center', gap:4 }}>
              Details <ArrowRight size={13}/>
            </Link>
          </div>
          {loading ? (
            <div>
              <div className="skeleton" style={{ height:20, marginBottom:12 }}/>
              <div className="skeleton" style={{ height:16, width:'70%' }}/>
            </div>
          ) : (
            <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
              {[
                { label:'Winning Model', val: modelInfo?.winner_model || 'XGBoost Learned Ranking', color:'#10b981' },
                { label:'NDCG@5',        val: (modelInfo?.metrics?.ndcg ?? 0.607).toFixed(3),       color:'#3b82f6' },
                { label:'Precision@5',   val: (modelInfo?.metrics?.precision ?? 0.316).toFixed(3),  color:'#818cf8' },
                { label:'Last Trained',  val: 'Today at 09:14',                                     color:'var(--text-secondary)' },
              ].map(r => (
                <div key={r.label} style={{ display:'flex', justifyContent:'space-between', alignItems:'center', padding:'8px 12px', background:'var(--bg-surface)', borderRadius:'var(--radius-sm)' }}>
                  <span style={{ fontSize:13, color:'var(--text-secondary)' }}>{r.label}</span>
                  <span style={{ fontSize:13, fontWeight:600, color:r.color }}>{r.val}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Quick Actions */}
        <div className="card">
          <h4 style={{ marginBottom:20 }}>Quick Actions</h4>
          <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
            {quickActions.map(a => (
              <Link key={a.to} to={a.to} style={{
                display:'flex', alignItems:'center', gap:12, padding:'12px 14px',
                background:'var(--bg-surface)', border:'1px solid var(--border)',
                borderRadius:'var(--radius-sm)', transition:'all .2s', color:'var(--text-primary)',
              }}
                onMouseEnter={e => { e.currentTarget.style.borderColor='var(--border-glow)'; e.currentTarget.style.background='var(--bg-card-hover)'; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor='var(--border)'; e.currentTarget.style.background='var(--bg-surface)'; }}>
                <div style={{ width:32,height:32,borderRadius:8,background:`${a.color}18`,border:`1px solid ${a.color}30`,display:'flex',alignItems:'center',justifyContent:'center' }}>
                  <a.icon size={15} color={a.color}/>
                </div>
                <span style={{ flex:1, fontSize:14 }}>{a.label}</span>
                <ArrowRight size={14} style={{ color:'var(--text-muted)' }}/>
              </Link>
            ))}
          </div>
        </div>
      </div>

      {/* Recent Events */}
      <div className="card mt-6">
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:20 }}>
          <h4>Recent Tracking Events</h4>
          <span className="badge badge-green" style={{ display:'flex',alignItems:'center',gap:5 }}>
            <span style={{ width:6,height:6,borderRadius:'50%',background:'var(--success)' }}/>Live
          </span>
        </div>
        <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
          {RECENT_EVENTS.map(ev => (
            <div key={ev.id} style={{ display:'flex', alignItems:'center', gap:12, padding:'10px 14px', background:'var(--bg-surface)', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
              <span className="badge" style={{ background:`${EVENT_COLOR[ev.event]}18`, color:EVENT_COLOR[ev.event], border:`1px solid ${EVENT_COLOR[ev.event]}30`, minWidth:80, justifyContent:'center' }}>{ev.event}</span>
              <code style={{ fontSize:12, color:'var(--text-muted)', fontFamily:'monospace' }}>{ev.customer}</code>
              <span style={{ flex:1, fontSize:13 }}>{ev.product}</span>
              <span style={{ fontSize:12, color:'var(--text-muted)' }}>{ev.time}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
