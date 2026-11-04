import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { getDashboardOverview, getDashboardEvents, getMe } from '../../api/client';
import { Brain, Key, BarChart3, Zap, ArrowRight, RefreshCw, CheckCircle2, AlertCircle, Clock } from 'lucide-react';

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

const EVENT_COLOR = {
  view: '#3b82f6',
  click: '#818cf8',
  add_to_cart: '#f59e0b',
  purchase: '#10b981',
};

export default function Overview() {
  const { user, setUser } = useAuth();
  const [overview, setOverview] = useState(null);
  const [events,   setEvents]   = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = useCallback(async (isInitial = false) => {
    if (isInitial) setLoading(true);
    else setRefreshing(true);

    try {
      const [meRes, ovRes, evRes] = await Promise.allSettled([
        getMe(),
        getDashboardOverview(),
        getDashboardEvents(20),
      ]);

      if (meRes.status === 'fulfilled') setUser(meRes.value);
      if (ovRes.status === 'fulfilled') setOverview(ovRes.value);
      if (evRes.status === 'fulfilled') setEvents(evRes.value?.events || []);
    } catch {
      // Graceful fallback to empty state
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [setUser]);

  useEffect(() => {
    loadData(true);

    // Auto-refresh every 30 seconds while tab is visible
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') {
        loadData(false);
      }
    }, 30000);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        loadData(false);
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [loadData]);

  const quickActions = [
    { to:'/onboarding/upload', label:'Upload New Dataset', icon:Zap,      color:'#3b82f6' },
    { to:'/dashboard/keys',    label:'View API Keys',       icon:Key,      color:'#818cf8' },
    { to:'/dashboard/model',   label:'Re-train Model',      icon:Brain,    color:'#10b981' },
    { to:'/dashboard/analytics',label:'View Analytics',     icon:BarChart3,color:'#06b6d4' },
  ];

  const formatLastTrained = (ts) => {
    if (!ts) return 'Never trained';
    try {
      const d = new Date(ts);
      return d.toLocaleDateString(undefined, { month:'short', day:'numeric' }) + ' at ' + d.toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' });
    } catch {
      return ts;
    }
  };

  return (
    <div>
      {/* Header */}
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:32 }}>
        <div>
          <h3 style={{ marginBottom:4 }}>Welcome back{user?.company_name ? `, ${user.company_name}` : ''} 👋</h3>
          <p style={{ fontSize:14 }}>Here's what's happening with your recommendation engine.</p>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:12 }}>
          {refreshing && (
            <span style={{ fontSize:12, color:'var(--text-muted)', display:'flex', alignItems:'center', gap:6 }}>
              <RefreshCw size={12} className="animate-spin"/> Updating…
            </span>
          )}
          {!user?.email_verified && (
            <div className="badge badge-yellow"><AlertCircle size={12}/> Email not verified</div>
          )}
          {user?.email_verified && (
            <div className="badge badge-green"><CheckCircle2 size={12}/> Verified</div>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="grid-4 mb-8">
        <StatCard
          label="Model Status"
          value={loading ? '…' : overview?.status || 'Not Started'}
          sub={overview?.ready ? 'Ready for live serving' : 'Awaiting training'}
          color="#10b981"
          icon={Brain}
        />
        <StatCard
          label="Tenant ID"
          value={user?.tenant_id || overview?.tenant_id || '—'}
          sub="Your identifier"
          color="#3b82f6"
          icon={Zap}
        />
        <StatCard
          label="Requests Today"
          value={loading ? '…' : (overview?.requests_today ?? 0).toLocaleString()}
          sub="Live recommendation calls"
          color="#818cf8"
          icon={BarChart3}
        />
        <StatCard
          label="Active API Keys"
          value={loading ? '…' : String(overview?.active_key_count ?? 0)}
          sub="Configured credentials"
          color="#06b6d4"
          icon={Key}
        />
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
                {
                  label: 'Winning Model',
                  val: overview?.winning_model || (overview?.ready ? 'Deployed' : 'None yet'),
                  color: overview?.winning_model ? '#10b981' : 'var(--text-muted)',
                },
                {
                  label: 'NDCG@5',
                  val: overview?.metrics?.ndcg != null ? Number(overview.metrics.ndcg).toFixed(3) : '—',
                  color: overview?.metrics?.ndcg != null ? '#3b82f6' : 'var(--text-muted)',
                },
                {
                  label: 'Precision@5',
                  val: overview?.metrics?.precision != null ? Number(overview.metrics.precision).toFixed(3) : '—',
                  color: overview?.metrics?.precision != null ? '#818cf8' : 'var(--text-muted)',
                },
                {
                  label: 'Last Trained',
                  val: formatLastTrained(overview?.last_trained),
                  color: 'var(--text-secondary)',
                },
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
        {loading ? (
          <div>
            <div className="skeleton" style={{ height:36, marginBottom:8 }}/>
            <div className="skeleton" style={{ height:36, marginBottom:8 }}/>
            <div className="skeleton" style={{ height:36 }}/>
          </div>
        ) : events.length === 0 ? (
          <div style={{ textAlign:'center', padding:'32px 16px', color:'var(--text-muted)' }}>
            <Clock size={28} style={{ opacity:0.4, marginBottom:10 }}/>
            <p style={{ fontSize:14, margin:0 }}>No client tracking events recorded yet.</p>
            <p style={{ fontSize:12, color:'var(--text-secondary)', marginTop:4 }}>
              Events streamed from your storefront SDK will appear here in real time.
            </p>
          </div>
        ) : (
          <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
            {events.map((ev, idx) => {
              const evColor = EVENT_COLOR[ev.event_type] || '#3b82f6';
              return (
                <div key={ev.ts || idx} style={{ display:'flex', alignItems:'center', gap:12, padding:'10px 14px', background:'var(--bg-surface)', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
                  <span className="badge" style={{ background:`${evColor}18`, color:evColor, border:`1px solid ${evColor}30`, minWidth:80, justifyContent:'center' }}>
                    {ev.event_type}
                  </span>
                  <code style={{ fontSize:12, color:'var(--text-muted)', fontFamily:'monospace' }}>
                    {ev.customer_id || ev.session_id || 'anonymous'}
                  </code>
                  <span style={{ flex:1, fontSize:13 }}>
                    {ev.product_name || ev.product_id || '—'}
                  </span>
                  <span style={{ fontSize:12, color:'var(--text-muted)' }}>
                    {ev.time_ago || 'recent'}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
