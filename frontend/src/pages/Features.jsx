import { useState, useRef, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Navbar from '../components/Navbar';
import {
  Brain, BarChart3, Zap, ShieldCheck, Rocket, Globe,
  Code2, Database, Cpu, RefreshCw, Key, Lock, Eye,
  CheckCircle2, ArrowRight, Star, ChevronDown,
  Package, Layers, Server, Webhook, ToggleLeft,
} from 'lucide-react';

/* ── Fade-in hook ───────────────────────────────────────────── */
function RevealDiv({ children, delay = 0, style = {}, ...props }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) {
        el.style.opacity = '1';
        el.style.transform = 'translateY(0)';
        obs.disconnect();
      }
    }, { threshold: 0.08 });
    el.style.opacity = '0';
    el.style.transform = 'translateY(24px)';
    el.style.transition = `opacity .55s ease ${delay}ms, transform .55s ease ${delay}ms`;
    obs.observe(el);
    return () => obs.disconnect();
  }, [delay]);
  return <div ref={ref} style={style} {...props}>{children}</div>;
}

/* ── Feature category ───────────────────────────────────────── */
const CATEGORIES = [
  {
    id: 'core',
    label: 'Core AI',
    icon: Brain,
    color: '#818cf8',
    tagline: 'Models that compete, not guess.',
    features: [
      {
        icon: Brain,     color: '#818cf8',
        title: 'Domain-Agnostic Intelligence',
        desc:  'Works out of the box for E-commerce, Telecom, Grocery, Fashion, and SaaS — no vertical-specific code needed.',
        detail: 'The GenericConfigAdapter maps any schema using AI column profiling. The same pipeline that handles a Telco\'s service matrix handles a fashion brand\'s product catalog.',
        tags: ['Auto-schema', 'Multi-vertical', 'Zero config'],
      },
      {
        icon: BarChart3, color: '#3b82f6',
        title: 'Autonomous Model Selection',
        desc:  '4 algorithms train simultaneously on a stratified split. NDCG@5-ranked winner deploys automatically.',
        detail: 'Content-Based (cosine similarity), Collaborative Filtering (TruncatedSVD), Dynamic Hybrid (rank blend), and XGBoost Learned Ranking compete every training run.',
        tags: ['4 models', 'NDCG@5', 'Auto-deploy'],
      },
      {
        icon: RefreshCw, color: '#06b6d4',
        title: 'One-Click Retraining',
        desc:  'Upload a new dataset, hit retrain. The full model competition reruns with fresh data in minutes.',
        detail: 'Training status is polled in real-time via /v1/onboard/status. Winner metrics are surfaced directly in your dashboard with before/after comparison.',
        tags: ['Incremental', 'Status polling', 'Metrics diff'],
      },
    ],
  },
  {
    id: 'data',
    label: 'Data Handling',
    icon: Database,
    color: '#3b82f6',
    tagline: 'Ingest anything. Profile everything.',
    features: [
      {
        icon: Database,  color: '#3b82f6',
        title: 'Universal Data Ingestion',
        desc:  'Upload CSV, Parquet, or JSON. The AI profiler detects schema, cardinality, ID columns, and interaction types.',
        detail: 'The profiler runs structural analysis — detecting customer_id, product_id, timestamp, and implicit interaction columns without you specifying them.',
        tags: ['CSV', 'Parquet', 'JSON', 'Auto-detect'],
      },
      {
        icon: Cpu,       color: '#818cf8',
        title: 'Transactional & Service Matrix',
        desc:  'Two interaction models supported: event-row transactional data and wide-format service matrices.',
        detail: 'Transactional mode (one row per event) and Service Matrix mode (one row per customer, columns = subscribed services) are both natively supported and auto-detected.',
        tags: ['Transactional', 'Wide format', 'Auto-classify'],
      },
      {
        icon: Server,    color: '#06b6d4',
        title: 'S3 & Shopify Native',
        desc:  'Pull from AWS S3 buckets or connect Shopify OAuth. Enterprise data stays in your cloud.',
        detail: 'SQS-backed async ingestion keeps large datasets flowing without timeouts. Shopify OAuth lets merchants connect their product and order history with one click.',
        tags: ['AWS S3', 'SQS', 'Shopify OAuth'],
      },
    ],
  },
  {
    id: 'api',
    label: 'API & SDK',
    icon: Code2,
    color: '#06b6d4',
    tagline: 'Drop-in recommendations for any stack.',
    features: [
      {
        icon: Zap,       color: '#06b6d4',
        title: '25KB Lightweight SDK',
        desc:  'Zero dependencies. Drops into any HTML page with a single script tag. Tracks events and renders recommendations.',
        detail: 'The SDK automatically identifies anonymous sessions, queues events during offline periods, and handles identity merging when users log in.',
        tags: ['25KB', 'No deps', 'Auto-identity'],
      },
      {
        icon: Globe,     color: '#10b981',
        title: 'Sub-200ms REST API',
        desc:  'GET /v1/recommendations returns a ranked list in under 200ms. Cold-start fallback is built-in.',
        detail: 'Recommendation responses include rank, product_id, product_name, and a fallback flag. The API uses pub/pk key auth — public key for client-side, private for server-side.',
        tags: ['<200ms', 'Fallback', 'Ranked results'],
      },
      {
        icon: Webhook,   color: '#f59e0b',
        title: 'Webhook & SQS Events',
        desc:  'Real-time event streaming via SQS for high-volume tracking without synchronous API calls.',
        detail: 'Track events fire-and-forget via POST /v1/track. High-volume environments can push to SQS directly — the backend processes and re-attributes asynchronously.',
        tags: ['SQS', 'Async', 'High-volume'],
      },
    ],
  },
  {
    id: 'security',
    label: 'Security & Isolation',
    icon: ShieldCheck,
    color: '#10b981',
    tagline: 'Every tenant is an island.',
    features: [
      {
        icon: ShieldCheck, color: '#10b981',
        title: 'Multi-Tenant Isolation',
        desc:  'Hard data boundary between every tenant. No cross-tenant query, data access, or model contamination.',
        detail: 'Tenant ID is embedded into every storage path, model filename, and API key scope. A misconfigured request will never return another tenant\'s data.',
        tags: ['Hard isolation', 'Scoped keys', 'No leakage'],
      },
      {
        icon: Key,       color: '#3b82f6',
        title: 'Public / Private Key Pair',
        desc:  'Public key for client-side embedding (safe to expose). Private key for server-side operations only.',
        detail: 'The public key can only call GET /v1/recommendations and POST /v1/track. The private key unlocks onboarding, retraining, and account management.',
        tags: ['pk-live-…', 'sk-live-…', 'Scoped access'],
      },
      {
        icon: RefreshCw, color: '#818cf8',
        title: 'Instant Key Rotation',
        desc:  'Rotate keys with one click. Old keys are invalidated immediately. New pair issued instantly.',
        detail: 'Built for security-conscious teams — if a key is suspected compromised, rotation is a single dashboard action with no service interruption for configured systems.',
        tags: ['Instant', 'Audit log', 'Zero downtime'],
      },
    ],
  },
  {
    id: 'ops',
    label: 'Operations',
    icon: Rocket,
    color: '#f59e0b',
    tagline: 'From signup to live in under 10 minutes.',
    features: [
      {
        icon: Rocket,    color: '#f59e0b',
        title: 'Zero-Code Onboarding',
        desc:  '5-step wizard: upload → schema map → confirm config → train → integrate. No CLI, no YAML, no config files.',
        detail: 'The wizard generates TenantConfig YAML, validates column mappings, starts training, and provides a copy-paste integration snippet — all in one flow.',
        tags: ['5 steps', '<10 min', 'No CLI'],
      },
      {
        icon: ToggleLeft, color: '#06b6d4',
        title: 'Cold-Start Fallback',
        desc:  'New customers or sparse profiles automatically fall back to popularity-based recommendations.',
        detail: 'Cold-start is handled natively — the response includes a `fallback: true` flag so your frontend can optionally show a different label ("Popular picks" vs "For you").',
        tags: ['Smart fallback', 'Flag in response', 'No 404s'],
      },
      {
        icon: BarChart3, color: '#10b981',
        title: 'Live Analytics Dashboard',
        desc:  'Track event volume, CTR, fallback rate, and top recommended products — updated in real time.',
        detail: 'The dashboard surfaces NDCG@5, Precision@5, and Recall@5 from the last training run alongside week-on-week tracking event trends.',
        tags: ['CTR', 'NDCG@5', 'Event trends'],
      },
    ],
  },
];

/* ── Comparison table ───────────────────────────────────────── */
const COMPARE = [
  { label: 'Setup time',         aipod: 'Under 10 min',  others: '2–6 weeks'     },
  { label: 'ML expertise needed',aipod: 'None',           others: 'Data scientist'},
  { label: 'Models tested',      aipod: '4 competing',   others: '1 fixed model' },
  { label: 'Cold-start handling',aipod: 'Built-in',      others: 'Manual config' },
  { label: 'Multi-tenant',       aipod: 'Hard isolation', others: 'Shared DB'    },
  { label: 'SDK size',           aipod: '25 KB',          others: '200–400 KB'   },
  { label: 'Pricing',            aipod: 'Free to start',  others: '$500+ / mo'   },
];

export default function Features() {
  const [activeTab, setActiveTab] = useState('core');
  const active = CATEGORIES.find(c => c.id === activeTab);

  return (
    <div style={{ overflow: 'hidden' }}>
      <Navbar />

      {/* ── Hero ─────────────────────────────────────────────── */}
      <section style={{ paddingTop: 140, paddingBottom: 72, textAlign: 'center', position: 'relative', overflow: 'hidden' }}>
        <div className="orb orb-purple" style={{ width: 500, height: 500, top: -120, left: -80, opacity: .5 }} />
        <div className="orb orb-cyan"   style={{ width: 400, height: 400, top: -80, right: -80, opacity: .4 }} />
        <div className="container" style={{ position: 'relative', zIndex: 1 }}>
          <RevealDiv>
            <div className="badge badge-cyan" style={{ display: 'inline-flex', marginBottom: 20 }}>
              <Zap size={12} /> Complete Feature Set
            </div>
          </RevealDiv>
          <RevealDiv delay={100}>
            <h1 style={{ maxWidth: 820, margin: '0 auto 20px' }}>
              Everything You Need to<br />
              <span className="gradient-text">Personalize at Scale</span>
            </h1>
          </RevealDiv>
          <RevealDiv delay={200}>
            <p style={{ maxWidth: 580, margin: '0 auto 40px', fontSize: 18 }}>
              From zero-config onboarding to sub-200ms recommendations, every part of the
              AI_POD platform is engineered to remove complexity and deliver results fast.
            </p>
          </RevealDiv>
          <RevealDiv delay={300}>
            <div style={{ display: 'flex', gap: 14, justifyContent: 'center', flexWrap: 'wrap' }}>
              <Link to="/signup" className="btn btn-primary btn-lg">
                Get Started Free <ArrowRight size={17} />
              </Link>
              <Link to="/how-it-works" className="btn btn-secondary btn-lg">
                See How It Works
              </Link>
            </div>
          </RevealDiv>

          {/* Quick stat pills */}
          <RevealDiv delay={400}>
            <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap', marginTop: 40 }}>
              {[
                { val: '4', label: 'AI Models' }, { val: '<10min', label: 'Setup' },
                { val: '25KB', label: 'SDK' },    { val: '0', label: 'ML required' },
              ].map(s => (
                <div key={s.label} style={{ padding: '8px 18px', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 99, display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontFamily: 'Outfit', fontWeight: 700, color: 'var(--accent-1)' }}>{s.val}</span>
                  <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{s.label}</span>
                </div>
              ))}
            </div>
          </RevealDiv>
        </div>
      </section>

      {/* ── Tabbed feature browser ────────────────────────────── */}
      <section className="section" style={{ background: 'var(--bg-surface)' }}>
        <div className="container">
          {/* Tab nav */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 48, justifyContent: 'center' }}>
            {CATEGORIES.map(cat => (
              <button key={cat.id} onClick={() => setActiveTab(cat.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '10px 20px', borderRadius: 99, fontSize: 14, fontWeight: 500,
                  border: `2px solid ${activeTab === cat.id ? cat.color : 'var(--border)'}`,
                  background: activeTab === cat.id ? `${cat.color}15` : 'transparent',
                  color: activeTab === cat.id ? cat.color : 'var(--text-secondary)',
                  cursor: 'pointer', transition: 'all .2s',
                }}>
                <cat.icon size={15} />
                {cat.label}
              </button>
            ))}
          </div>

          {/* Active category */}
          {active && (
            <div key={active.id}>
              <div style={{ textAlign: 'center', marginBottom: 40 }}>
                <div style={{ width: 56, height: 56, borderRadius: 16, background: `${active.color}15`, border: `1px solid ${active.color}30`, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px' }}>
                  <active.icon size={26} color={active.color} />
                </div>
                <h3 style={{ marginBottom: 8 }}>{active.label}</h3>
                <p style={{ color: active.color, fontStyle: 'italic', fontSize: 15 }}>{active.tagline}</p>
              </div>

              <div className="grid-3">
                {active.features.map((f, i) => (
                  <RevealDiv key={f.title} delay={i * 80}>
                    <FeatureCard {...f} accentColor={active.color} />
                  </RevealDiv>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>

      {/* ── Full feature grid ─────────────────────────────────── */}
      <section className="section">
        <div className="container">
          <RevealDiv style={{ textAlign: 'center', marginBottom: 56 }}>
            <div className="badge badge-blue" style={{ display: 'inline-flex', marginBottom: 16 }}>Complete Platform</div>
            <h2>All Features at a Glance</h2>
          </RevealDiv>
          <div className="grid-3" style={{ gap: 16 }}>
            {CATEGORIES.flatMap(cat =>
              cat.features.map(f => (
                <RevealDiv key={f.title} style={{ display: 'flex', alignItems: 'flex-start', gap: 14, padding: '16px 18px', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', transition: 'border-color .2s' }}
                  onMouseEnter={e => e.currentTarget.style.borderColor = `${f.color}50`}
                  onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}>
                  <div style={{ width: 36, height: 36, borderRadius: 9, background: `${f.color}12`, border: `1px solid ${f.color}25`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    <f.icon size={16} color={f.color} />
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{f.title}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>{f.desc}</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 8 }}>
                      {f.tags.map(t => <span key={t} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 99, background: `${f.color}10`, color: f.color, border: `1px solid ${f.color}20` }}>{t}</span>)}
                    </div>
                  </div>
                </RevealDiv>
              ))
            )}
          </div>
        </div>
      </section>

      {/* ── Comparison table ──────────────────────────────────── */}
      <section className="section" style={{ background: 'var(--bg-surface)' }}>
        <div className="container" style={{ maxWidth: 800 }}>
          <RevealDiv style={{ textAlign: 'center', marginBottom: 48 }}>
            <div className="badge badge-purple" style={{ display: 'inline-flex', marginBottom: 16 }}>vs. The Alternative</div>
            <h2>AI_POD vs <span className="gradient-text">Building It Yourself</span></h2>
          </RevealDiv>
          <RevealDiv>
            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-surface)' }}>
                    <th style={{ padding: '16px 20px', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 500 }}>Capability</th>
                    <th style={{ padding: '16px 20px', textAlign: 'center', color: 'var(--accent-1)', fontWeight: 700 }}>AI_POD</th>
                    <th style={{ padding: '16px 20px', textAlign: 'center', color: 'var(--text-muted)', fontWeight: 500 }}>Build-your-own</th>
                  </tr>
                </thead>
                <tbody>
                  {COMPARE.map((row, i) => (
                    <tr key={row.label} style={{ borderTop: '1px solid var(--border)', background: i % 2 ? 'rgba(59,130,246,.02)' : 'transparent' }}>
                      <td style={{ padding: '13px 20px', color: 'var(--text-secondary)' }}>{row.label}</td>
                      <td style={{ padding: '13px 20px', textAlign: 'center' }}>
                        <span style={{ color: 'var(--success)', fontWeight: 600 }}>{row.aipod}</span>
                      </td>
                      <td style={{ padding: '13px 20px', textAlign: 'center', color: 'var(--text-muted)' }}>{row.others}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </RevealDiv>
        </div>
      </section>

      {/* ── Social proof ─────────────────────────────────────── */}
      <section className="section">
        <div className="container" style={{ textAlign: 'center' }}>
          <RevealDiv>
            <div style={{ display: 'flex', gap: 6, justifyContent: 'center', marginBottom: 12 }}>
              {[1,2,3,4,5].map(i => <Star key={i} size={18} color="#f59e0b" fill="#f59e0b" />)}
            </div>
            <blockquote style={{ maxWidth: 560, margin: '0 auto 40px', fontSize: 18, fontStyle: 'italic', color: 'var(--text-secondary)', lineHeight: 1.8 }}>
              "We went from raw Telco CSV to live recommendations on our portal in under 15 minutes. The model that won had better NDCG than anything we'd built in-house."
            </blockquote>
            <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>— Early Access Customer · Telecom Vertical</div>
          </RevealDiv>
        </div>
      </section>

      {/* ── CTA ─────────────────────────────────────────────── */}
      <section className="section-sm">
        <div className="container">
          <RevealDiv>
            <div style={{ textAlign: 'center', padding: '64px 40px', background: 'linear-gradient(135deg,rgba(129,140,248,.12),rgba(6,182,212,.1))', border: '1px solid rgba(129,140,248,.2)', borderRadius: 'var(--radius-xl)', position: 'relative', overflow: 'hidden' }}>
              <div className="orb orb-purple" style={{ width: 300, height: 300, top: -80, right: -60 }} />
              <div className="orb orb-cyan"   style={{ width: 250, height: 250, bottom: -60, left: -40 }} />
              <div style={{ position: 'relative', zIndex: 1 }}>
                <h2 style={{ marginBottom: 14 }}>All these features,<br /><span className="gradient-text">free to get started.</span></h2>
                <p style={{ marginBottom: 32, maxWidth: 400, margin: '0 auto 32px' }}>
                  No credit card. No ML team. Just upload your data and go.
                </p>
                <div style={{ display: 'flex', gap: 14, justifyContent: 'center', flexWrap: 'wrap' }}>
                  <Link to="/signup" className="btn btn-primary btn-lg">
                    Create Free Account <ArrowRight size={17} />
                  </Link>
                  <Link to="/how-it-works" className="btn btn-secondary btn-lg">
                    How It Works
                  </Link>
                </div>
              </div>
            </div>
          </RevealDiv>
        </div>
      </section>

      {/* Footer */}
      <footer style={{ borderTop: '1px solid var(--border)', padding: '32px 0' }}>
        <div className="container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
          <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 28, height: 28, borderRadius: 7, background: 'linear-gradient(135deg,#3b82f6,#818cf8)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Zap size={13} color="#fff" /></div>
            <span style={{ fontFamily: 'Outfit', fontWeight: 700 }}>AI_POD</span>
          </Link>
          <div style={{ display: 'flex', gap: 20, fontSize: 13, color: 'var(--text-muted)' }}>
            <Link to="/">Home</Link>
            <Link to="/how-it-works">How It Works</Link>
            <Link to="/signup">Get Started</Link>
            <Link to="/signin">Sign In</Link>
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>© 2026 AI_POD</div>
        </div>
      </footer>
    </div>
  );
}

/* ── Feature detail card ───────────────────────────────────── */
function FeatureCard({ icon: Icon, color, accentColor, title, desc, detail, tags }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card" style={{ cursor: 'pointer', transition: 'border-color .2s', border: `1px solid ${open ? `${color}40` : 'var(--border)'}` }}
      onClick={() => setOpen(o => !o)}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 14 }}>
        <div style={{ width: 44, height: 44, borderRadius: 12, background: `${color}15`, border: `1px solid ${color}25`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
          <Icon size={20} color={color} />
        </div>
        <div style={{ flex: 1 }}>
          <h4 style={{ fontSize: 15, marginBottom: 6 }}>{title}</h4>
          <p style={{ fontSize: 13 }}>{desc}</p>
        </div>
        <ChevronDown size={16} color="var(--text-muted)" style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .2s', flexShrink: 0 }} />
      </div>
      {open && (
        <div style={{ paddingTop: 14, borderTop: '1px solid var(--border)', animation: 'fadeUp .25s ease' }}>
          <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.7, marginBottom: 12 }}>{detail}</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {tags.map(t => (
              <span key={t} style={{ fontSize: 11, padding: '3px 9px', borderRadius: 99, background: `${color}10`, color, border: `1px solid ${color}25` }}>{t}</span>
            ))}
          </div>
        </div>
      )}
      <style>{`@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}`}</style>
    </div>
  );
}
