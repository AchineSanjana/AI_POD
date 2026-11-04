import { useEffect, useState } from 'react';
import { getDashboardAnalytics } from '../../api/client';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { BarChart3, Info } from 'lucide-react';

const TOOLTIP_STYLE = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  color: 'var(--text-primary)',
  fontSize: 12,
};

export default function Analytics() {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState('');

  useEffect(() => {
    const load = async () => {
      try {
        const res = await getDashboardAnalytics(7);
        setData(res);
      } catch (err) {
        setError(err?.message || 'Failed to load analytics telemetry');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const totalEvents = data?.total_events ?? 0;
  const totalRecs = data?.total_recommendations ?? 0;
  const eventsByDay = data?.events_by_day || [];
  const topProducts = data?.top_products || [];

  return (
    <div>
      <div style={{ marginBottom:32 }}>
        <h3 style={{ marginBottom:8 }}>Analytics</h3>
        <p style={{ fontSize:14 }}>Tracking event volume and recommendation performance over the last 7 days.</p>
      </div>

      {error && <div className="alert alert-error mb-6">{error}</div>}

      {/* Stat pills */}
      <div className="grid-4 mb-8">
        {[
          {
            label: 'Total Events',
            val: loading ? '…' : totalEvents.toLocaleString(),
            sub: 'Streamed interactions',
            color: '#3b82f6',
          },
          {
            label: 'Recommendations',
            val: loading ? '…' : totalRecs.toLocaleString(),
            sub: 'Live API scoring calls',
            color: '#818cf8',
          },
          {
            label: 'CTR',
            val: loading ? '…' : (data?.ctr != null ? `${(data.ctr * 100).toFixed(1)}%` : '—'),
            sub: data?.ctr != null ? 'Click-through rate' : 'No conversion tracking',
            color: '#10b981',
          },
          {
            label: 'Fallback Rate',
            val: loading ? '…' : (data?.fallback_rate != null ? `${(data.fallback_rate * 100).toFixed(1)}%` : '—'),
            sub: data?.fallback_rate != null ? 'Popularity fallback' : 'No score data',
            color: '#f59e0b',
          },
        ].map(s => (
          <div key={s.label} className="card" style={{ textAlign:'center' }}>
            <div style={{ fontSize:11, color:'var(--text-muted)', marginBottom:6, textTransform:'uppercase', letterSpacing:1 }}>
              {s.label}
            </div>
            <div style={{ fontFamily:'Outfit', fontWeight:700, fontSize:'1.6rem', color:s.color }}>
              {s.val}
            </div>
            <div style={{ fontSize:12, color:'var(--text-muted)', marginTop:4 }}>
              {s.sub}
            </div>
          </div>
        ))}
      </div>

      {/* Event volume line chart */}
      <div className="card mb-6">
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:24 }}>
          <h4 style={{ margin:0 }}>Event Volume — Last 7 Days</h4>
          <span style={{ fontSize:12, color:'var(--text-muted)' }}>Excludes wizard tests</span>
        </div>

        {loading ? (
          <div className="skeleton" style={{ height:260 }}/>
        ) : totalEvents === 0 ? (
          <div style={{ textAlign:'center', padding:'48px 16px', color:'var(--text-muted)' }}>
            <BarChart3 size={32} style={{ opacity:0.35, marginBottom:12 }}/>
            <p style={{ fontSize:14, margin:0 }}>No client interaction events recorded in the last 7 days.</p>
            <p style={{ fontSize:12, color:'var(--text-secondary)', marginTop:4 }}>
              Events tracked via <code>POST /v1/track</code> or the JavaScript SDK will be plotted here.
            </p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={eventsByDay}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(99,179,237,.08)"/>
              <XAxis dataKey="day" stroke="var(--text-muted)" tick={{ fontSize:12 }}/>
              <YAxis stroke="var(--text-muted)" tick={{ fontSize:12 }} allowDecimals={false}/>
              <Tooltip contentStyle={TOOLTIP_STYLE}/>
              <Legend wrapperStyle={{ fontSize:12 }}/>
              <Line type="monotone" dataKey="views"     stroke="#3b82f6" strokeWidth={2} dot={false}/>
              <Line type="monotone" dataKey="clicks"    stroke="#818cf8" strokeWidth={2} dot={false}/>
              <Line type="monotone" dataKey="cart_adds" stroke="#f59e0b" strokeWidth={2} dot={false}/>
              <Line type="monotone" dataKey="purchases" stroke="#10b981" strokeWidth={2} dot={false}/>
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Top products bar chart */}
      <div className="card">
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:24 }}>
          <h4 style={{ margin:0 }}>Top Recommended Products</h4>
          <span style={{ fontSize:12, color:'var(--text-muted)' }}>Past 7 days</span>
        </div>

        {loading ? (
          <div className="skeleton" style={{ height:220 }}/>
        ) : topProducts.length === 0 ? (
          <div style={{ textAlign:'center', padding:'40px 16px', color:'var(--text-muted)' }}>
            <Info size={28} style={{ opacity:0.35, marginBottom:10 }}/>
            <p style={{ fontSize:14, margin:0 }}>No product recommendation impressions recorded yet.</p>
            <p style={{ fontSize:12, color:'var(--text-secondary)', marginTop:4 }}>
              As customer recommendations are queried, most-recommended items will appear here.
            </p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={topProducts} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(99,179,237,.08)" horizontal={false}/>
              <XAxis type="number" stroke="var(--text-muted)" tick={{ fontSize:12 }} allowDecimals={false}/>
              <YAxis dataKey="name" type="category" stroke="var(--text-muted)" tick={{ fontSize:12 }} width={120}/>
              <Tooltip contentStyle={TOOLTIP_STYLE}/>
              <Bar dataKey="recs" fill="url(#recGrad)" radius={[0,4,4,0]}/>
              <defs>
                <linearGradient id="recGrad" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%"   stopColor="#3b82f6"/>
                  <stop offset="100%" stopColor="#818cf8"/>
                </linearGradient>
              </defs>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
