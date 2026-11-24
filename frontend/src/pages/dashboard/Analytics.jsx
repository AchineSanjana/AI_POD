import { useEffect, useState } from 'react';
import { getDashboardAnalytics } from '../../api/client';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts';
import { BarChart3, Info, Layers, Sparkles } from 'lucide-react';

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

  // Similar products fields
  const similarRequests = data?.similar_requests ?? 0;
  const similarClicks = data?.similar_clicks ?? 0;
  const similarAddCards = data?.similar_add_to_carts ?? 0;
  const similarPurchases = data?.similar_purchases ?? 0;
  const similarCtr = data?.similar_ctr;
  const topSimilarSources = data?.top_similar_source_products || [];

  // Personalised recommendations fields
  const recClicks = data?.recommendation_clicks ?? 0;
  const recCtr = data?.recommendation_ctr;
  const recAddCards = data?.recommendation_add_to_carts ?? 0;
  const recPurchases = data?.recommendation_purchases ?? 0;

  const isSimilarEmpty =
    similarRequests === 0 &&
    similarClicks === 0 &&
    similarAddCards === 0 &&
    similarPurchases === 0;

  const funnelData = [
    { stage: 'Requests', count: similarRequests, fill: '#3b82f6' },
    { stage: 'Clicks', count: similarClicks, fill: '#818cf8' },
    { stage: 'Add to Carts', count: similarAddCards, fill: '#f59e0b' },
    { stage: 'Purchases', count: similarPurchases, fill: '#10b981' },
  ];

  return (
    <div>
      <div style={{ marginBottom:32 }}>
        <h3 style={{ marginBottom:8 }}>Analytics</h3>
        <p style={{ fontSize:14 }}>Tracking event volume, recommendation conversion, and similar products telemetry over the last 7 days.</p>
      </div>

      {error && <div className="alert alert-error mb-6">{error}</div>}

      {/* Primary recommendation stat pills */}
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
            sub: 'Click-through rate',
            color: '#10b981',
            tooltip: 'Share of requests that received at least one click.',
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
            <div style={{ display:'flex', alignItems:'center', justifyContent:'center', gap:4 }}>
              <span style={{ fontFamily:'Outfit', fontWeight:700, fontSize:'1.6rem', color:s.color }}>
                {s.val}
              </span>
              {s.tooltip && (
                <span title={s.tooltip} style={{ cursor:'help', display:'inline-flex' }}>
                  <Info size={13} color="var(--text-muted)"/>
                </span>
              )}
            </div>
            <div style={{ fontSize:12, color:'var(--text-muted)', marginTop:4 }}>
              {s.sub}
            </div>
          </div>
        ))}
      </div>

      {/* Personalised Recommendations Mini-Block */}
      <div className="card mb-8">
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:16 }}>
          <div style={{ display:'flex', alignItems:'center', gap:8 }}>
            <Sparkles size={16} color="var(--accent-1)"/>
            <h4 style={{ margin:0 }}>Personalised Recommendations</h4>
          </div>
          <span style={{ fontSize:12, color:'var(--text-muted)' }}>Customer Model Performance</span>
        </div>

        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(180px, 1fr))', gap:16 }}>
          <div style={{ background:'var(--bg-surface)', padding:'12px 16px', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
            <div style={{ fontSize:11, color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:0.5 }}>Clicks</div>
            <div style={{ fontSize:'1.4rem', fontWeight:700, color:'var(--text-primary)', marginTop:4 }}>
              {loading ? '…' : recClicks.toLocaleString()}
            </div>
          </div>

          <div style={{ background:'var(--bg-surface)', padding:'12px 16px', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
            <div style={{ display:'flex', alignItems:'center', gap:4 }}>
              <span style={{ fontSize:11, color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:0.5 }}>CTR</span>
              <span title="Share of requests that received at least one click." style={{ cursor:'help', display:'inline-flex' }}>
                <Info size={11} color="var(--text-muted)"/>
              </span>
            </div>
            <div style={{ fontSize:'1.4rem', fontWeight:700, color:'#10b981', marginTop:4 }}>
              {loading ? '…' : (recCtr != null ? `${(recCtr * 100).toFixed(1)}%` : '—')}
            </div>
          </div>

          <div style={{ background:'var(--bg-surface)', padding:'12px 16px', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
            <div style={{ fontSize:11, color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:0.5 }}>Add to Carts</div>
            <div style={{ fontSize:'1.4rem', fontWeight:700, color:'#f59e0b', marginTop:4 }}>
              {loading ? '…' : recAddCards.toLocaleString()}
            </div>
          </div>

          <div style={{ background:'var(--bg-surface)', padding:'12px 16px', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
            <div style={{ fontSize:11, color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:0.5 }}>Purchases</div>
            <div style={{ fontSize:'1.4rem', fontWeight:700, color:'#10b981', marginTop:4 }}>
              {loading ? '…' : recPurchases.toLocaleString()}
            </div>
          </div>
        </div>
      </div>

      {/* Similar Products Section */}
      <div className="card mb-8" id="similar-products-analytics-section">
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:20 }}>
          <div style={{ display:'flex', alignItems:'center', gap:10 }}>
            <Layers size={18} color="var(--accent-2)"/>
            <h4 style={{ margin:0 }}>Similar Products</h4>
          </div>
          <span style={{ fontSize:12, color:'var(--text-muted)' }}>Storefront Similar Engine</span>
        </div>

        {/* Similar Stats Grid */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(160px, 1fr))', gap:14, marginBottom:24 }}>
          <div style={{ background:'var(--bg-surface)', padding:'12px 16px', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
            <div style={{ fontSize:11, color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:0.5 }}>Requests</div>
            <div style={{ fontSize:'1.4rem', fontWeight:700, color:'var(--text-primary)', marginTop:4 }}>
              {loading ? '…' : similarRequests.toLocaleString()}
            </div>
          </div>

          <div style={{ background:'var(--bg-surface)', padding:'12px 16px', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
            <div style={{ fontSize:11, color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:0.5 }}>Clicks</div>
            <div style={{ fontSize:'1.4rem', fontWeight:700, color:'#818cf8', marginTop:4 }}>
              {loading ? '…' : similarClicks.toLocaleString()}
            </div>
          </div>

          <div style={{ background:'var(--bg-surface)', padding:'12px 16px', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
            <div style={{ fontSize:11, color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:0.5 }}>Add to Carts</div>
            <div style={{ fontSize:'1.4rem', fontWeight:700, color:'#f59e0b', marginTop:4 }}>
              {loading ? '…' : similarAddCards.toLocaleString()}
            </div>
          </div>

          <div style={{ background:'var(--bg-surface)', padding:'12px 16px', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
            <div style={{ fontSize:11, color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:0.5 }}>Purchases</div>
            <div style={{ fontSize:'1.4rem', fontWeight:700, color:'#10b981', marginTop:4 }}>
              {loading ? '…' : similarPurchases.toLocaleString()}
            </div>
          </div>

          <div style={{ background:'var(--bg-surface)', padding:'12px 16px', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
            <div style={{ display:'flex', alignItems:'center', gap:4 }}>
              <span style={{ fontSize:11, color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:0.5 }}>CTR</span>
              <span title="Share of requests that received at least one click." style={{ cursor:'help', display:'inline-flex' }}>
                <Info size={11} color="var(--text-muted)"/>
              </span>
            </div>
            <div style={{ fontSize:'1.4rem', fontWeight:700, color:'#10b981', marginTop:4 }}>
              {loading ? '…' : (similarCtr != null ? `${(similarCtr * 100).toFixed(1)}%` : '—')}
            </div>
          </div>
        </div>

        {/* Empty state or Funnel + Top Compared */}
        {loading ? (
          <div className="skeleton" style={{ height:240 }}/>
        ) : isSimilarEmpty ? (
          <div style={{ textAlign:'center', padding:'48px 16px', color:'var(--text-muted)', background:'var(--bg-surface)', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
            <Layers size={32} style={{ opacity:0.35, marginBottom:12 }}/>
            <p style={{ fontSize:14, margin:0, fontWeight:500 }}>
              No similar-product activity yet. Add the SDK snippet from the Integrate step to your product pages.
            </p>
          </div>
        ) : (
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(min(280px, 100%), 1fr))', gap:24 }}>
            {/* Conversion Funnel */}
            <div style={{ background:'var(--bg-surface)', padding:'16px 20px', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
              <h5 style={{ margin:'0 0 16px 0' }}>Similar Products Conversion Funnel</h5>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={funnelData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(99,179,237,.08)" vertical={false}/>
                  <XAxis dataKey="stage" stroke="var(--text-muted)" tick={{ fontSize:12 }}/>
                  <YAxis stroke="var(--text-muted)" tick={{ fontSize:12 }} allowDecimals={false}/>
                  <Tooltip contentStyle={TOOLTIP_STYLE}/>
                  <Bar dataKey="count" radius={[4,4,0,0]}/>
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Top products people compared */}
            <div style={{ background:'var(--bg-surface)', padding:'16px 20px', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
              <h5 style={{ margin:'0 0 16px 0' }}>Top products people compared</h5>
              {topSimilarSources.length === 0 ? (
                <div style={{ textAlign:'center', padding:'36px 12px', color:'var(--text-muted)', fontSize:13 }}>
                  No comparison queries recorded yet.
                </div>
              ) : (
                <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                  {topSimilarSources.map((item, idx) => (
                    <div
                      key={item.product_id || idx}
                      style={{
                        display:'flex',
                        alignItems:'center',
                        justifyContent:'space-between',
                        padding:'8px 12px',
                        background:'var(--bg-card)',
                        borderRadius:4,
                        border:'1px solid var(--border)',
                      }}
                    >
                      <div style={{ minWidth:0, flex:1, marginRight:12 }}>
                        <div style={{ fontSize:13, fontWeight:600, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>
                          {item.name || item.product_id}
                        </div>
                        <div style={{ fontSize:11, color:'var(--text-muted)' }}>ID: {item.product_id}</div>
                      </div>
                      <span className="badge badge-blue" style={{ fontSize:11 }}>
                        {item.recs} {item.recs === 1 ? 'query' : 'queries'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
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
