import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';

const DAILY = [
  { day:'Mon', views:420, clicks:180, purchases:42, cart_adds:95 },
  { day:'Tue', views:380, clicks:165, purchases:38, cart_adds:88 },
  { day:'Wed', views:510, clicks:220, purchases:55, cart_adds:110 },
  { day:'Thu', views:475, clicks:200, purchases:50, cart_adds:102 },
  { day:'Fri', views:620, clicks:280, purchases:71, cart_adds:145 },
  { day:'Sat', views:540, clicks:230, purchases:60, cart_adds:120 },
  { day:'Sun', views:490, clicks:210, purchases:52, cart_adds:108 },
];

const TOP_PRODUCTS = [
  { name:'Online Security', recs:1842 },
  { name:'Tech Support',    recs:1620 },
  { name:'Streaming TV',    recs:1405 },
  { name:'Device Protect',  recs:1238 },
  { name:'Online Backup',   recs:1105 },
];

const TOOLTIP_STYLE = {
  background:'var(--bg-card)', border:'1px solid var(--border)',
  borderRadius:8, color:'var(--text-primary)', fontSize:12,
};

export default function Analytics() {
  return (
    <div>
      <div style={{ marginBottom:32 }}>
        <h3 style={{ marginBottom:8 }}>Analytics</h3>
        <p style={{ fontSize:14 }}>Tracking event volume and recommendation performance over the last 7 days.</p>
      </div>

      {/* Stat pills */}
      <div className="grid-4 mb-8">
        {[
          { label:'Total Events',    val:'3,435', delta:'+18%', color:'#3b82f6' },
          { label:'Recommendations', val:'12,450',delta:'+24%', color:'#818cf8' },
          { label:'CTR',             val:'14.2%', delta:'+2.1%',color:'#10b981' },
          { label:'Fallback Rate',   val:'3.1%',  delta:'-0.8%',color:'#f59e0b' },
        ].map(s => (
          <div key={s.label} className="card" style={{ textAlign:'center' }}>
            <div style={{ fontSize:11, color:'var(--text-muted)', marginBottom:6, textTransform:'uppercase', letterSpacing:1 }}>{s.label}</div>
            <div style={{ fontFamily:'Outfit',fontWeight:700,fontSize:'1.6rem', color:s.color }}>{s.val}</div>
            <div style={{ fontSize:12, color:'var(--success)', marginTop:4 }}>{s.delta} this week</div>
          </div>
        ))}
      </div>

      {/* Event volume line chart */}
      <div className="card mb-6">
        <h4 style={{ marginBottom:24 }}>Event Volume — Last 7 Days</h4>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={DAILY}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(99,179,237,.08)"/>
            <XAxis dataKey="day" stroke="var(--text-muted)" tick={{ fontSize:12 }}/>
            <YAxis stroke="var(--text-muted)" tick={{ fontSize:12 }}/>
            <Tooltip contentStyle={TOOLTIP_STYLE}/>
            <Legend wrapperStyle={{ fontSize:12 }}/>
            <Line type="monotone" dataKey="views"     stroke="#3b82f6" strokeWidth={2} dot={false}/>
            <Line type="monotone" dataKey="clicks"    stroke="#818cf8" strokeWidth={2} dot={false}/>
            <Line type="monotone" dataKey="cart_adds" stroke="#f59e0b" strokeWidth={2} dot={false}/>
            <Line type="monotone" dataKey="purchases" stroke="#10b981" strokeWidth={2} dot={false}/>
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Top products bar chart */}
      <div className="card">
        <h4 style={{ marginBottom:24 }}>Top Recommended Products</h4>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={TOP_PRODUCTS} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(99,179,237,.08)" horizontal={false}/>
            <XAxis type="number" stroke="var(--text-muted)" tick={{ fontSize:12 }}/>
            <YAxis dataKey="name" type="category" stroke="var(--text-muted)" tick={{ fontSize:12 }} width={110}/>
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
      </div>
    </div>
  );
}
