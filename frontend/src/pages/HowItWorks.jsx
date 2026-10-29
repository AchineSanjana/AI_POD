import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import Navbar from '../components/Navbar';
import {
  Upload, Brain, Code2, ArrowRight, CheckCircle2,
  Database, Cpu, BarChart3, Globe, Zap, ChevronRight,
  FileText, Settings2, Layers, Play, Eye, ShoppingCart,
  MousePointer, CreditCard, RefreshCw, Server
} from 'lucide-react';

/* ── Intersection observer fade-in ─────────────────────────── */
function useReveal() {
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
    }, { threshold: 0.1 });
    el.style.opacity = '0';
    el.style.transform = 'translateY(28px)';
    el.style.transition = 'opacity .6s ease, transform .6s ease';
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  return ref;
}

function RevealDiv({ children, delay = 0, style = {}, ...props }) {
  const ref = useReveal();
  return (
    <div ref={ref} style={{ transitionDelay: `${delay}ms`, ...style }} {...props}>
      {children}
    </div>
  );
}

/* ── Step connector line ─────────────────────────────────────── */
function StepNumber({ n, color }) {
  return (
    <div style={{
      width: 56, height: 56, borderRadius: '50%', flexShrink: 0,
      background: `${color}18`, border: `2px solid ${color}40`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: 'Outfit', fontWeight: 800, fontSize: 20, color,
      boxShadow: `0 0 20px ${color}25`,
    }}>{n}</div>
  );
}

const STEPS = [
  {
    n: 1, color: '#3b82f6',
    icon: Upload,
    title: 'Upload Your Dataset',
    sub: 'Any format. Any schema. Auto-profiled in seconds.',
    bullets: [
      'Drag & drop CSV, Parquet, or JSON files',
      'AI profiles your schema — detects IDs, columns, data types',
      'Automatically classifies: Transactional vs Service Matrix',
      'Works with Shopify, S3, or local files',
    ],
    detail: 'Our profiler inspects every column, computes cardinality, infers column roles, and generates a TenantConfig — all without you writing a single line of configuration.',
    visual: [
      { label: 'File uploaded', icon: FileText,  color: '#3b82f6' },
      { label: 'Schema detected', icon: Eye,     color: '#818cf8' },
      { label: 'Config generated', icon: Settings2, color: '#06b6d4' },
    ],
  },
  {
    n: 2, color: '#818cf8',
    icon: Brain,
    title: '4 AI Models Compete',
    sub: 'The best algorithm wins. Automatically.',
    bullets: [
      'Content-Based — cosine similarity on feature profiles',
      'Collaborative Filtering — TruncatedSVD latent space',
      'Dynamic Hybrid — weighted rank blend with cold-start fallback',
      'Learned Ranking — XGBoost gradient-boosted classifier',
    ],
    detail: 'All four models train simultaneously on a stratified train/test split. Each is evaluated on NDCG@5, Precision@5, and Recall@5. The winner is retrained on 100% of your data and deployed automatically.',
    visual: [
      { label: 'NDCG@5: 0.951',   icon: BarChart3, color: '#10b981' },
      { label: 'Winner deployed', icon: Cpu,        color: '#f59e0b' },
      { label: 'Zero downtime',   icon: RefreshCw,  color: '#818cf8' },
    ],
  },
  {
    n: 3, color: '#06b6d4',
    icon: Code2,
    title: 'Embed & Personalize',
    sub: 'One script tag. Live recommendations everywhere.',
    bullets: [
      'Copy a single <script> snippet into your HTML',
      'Track events: views, clicks, add-to-cart, purchases',
      'Identity merging: anonymous sessions → logged-in customers',
      'Dynamic recommendation widget with custom templates',
    ],
    detail: 'The 25KB dependency-free SDK handles session persistence, event queuing, and identity resolution automatically. Recommendations render in your DOM with a single JavaScript call.',
    visual: [
      { label: 'SDK embedded',  icon: Globe,       color: '#06b6d4' },
      { label: 'Events tracked', icon: MousePointer, color: '#3b82f6' },
      { label: 'Recs rendered', icon: Layers,       color: '#818cf8' },
    ],
  },
];

const EVENT_WEIGHTS = [
  { event: 'purchase',     weight: 5.0, icon: CreditCard,    color: '#10b981', desc: 'Highest signal — confirmed intent' },
  { event: 'add_to_cart',  weight: 3.0, icon: ShoppingCart,  color: '#f59e0b', desc: 'Strong interest signal' },
  { event: 'click',        weight: 2.0, icon: MousePointer,  color: '#3b82f6', desc: 'Active engagement' },
  { event: 'view',         weight: 1.0, icon: Eye,           color: '#818cf8', desc: 'Passive awareness' },
];

export default function HowItWorks() {
  return (
    <div style={{ overflow: 'hidden' }}>
      <Navbar />

      {/* ── Hero ─────────────────────────────────────────────── */}
      <section style={{ paddingTop: 140, paddingBottom: 80, textAlign: 'center', position: 'relative', overflow: 'hidden' }}>
        <div className="orb orb-blue"   style={{ width: 500, height: 500, top: -150, right: -100, opacity: .5 }} />
        <div className="orb orb-purple" style={{ width: 400, height: 400, bottom: -80, left: -80, opacity: .4 }} />
        <div className="container" style={{ position: 'relative', zIndex: 1 }}>
          <RevealDiv>
            <div className="badge badge-purple" style={{ display: 'inline-flex', marginBottom: 20 }}>
              <Zap size={12} /> Step-by-Step Guide
            </div>
          </RevealDiv>
          <RevealDiv delay={100}>
            <h1 style={{ maxWidth: 780, margin: '0 auto 20px' }}>
              How AI_POD Works —<br />
              <span className="gradient-text">Data to Recommendations in 3 Steps</span>
            </h1>
          </RevealDiv>
          <RevealDiv delay={200}>
            <p style={{ maxWidth: 580, margin: '0 auto 40px', fontSize: 18 }}>
              No data scientists. No ML pipelines. No configuration files. Just upload your data and
              watch four algorithms compete to serve the best recommendations for your customers.
            </p>
          </RevealDiv>
          <RevealDiv delay={300}>
            <div style={{ display: 'flex', gap: 14, justifyContent: 'center', flexWrap: 'wrap' }}>
              <Link to="/signup" className="btn btn-primary btn-lg">
                Try It Free <ArrowRight size={17} />
              </Link>
              <Link to="/features" className="btn btn-secondary btn-lg">
                See All Features
              </Link>
            </div>
          </RevealDiv>
        </div>
      </section>

      {/* ── Steps ────────────────────────────────────────────── */}
      {STEPS.map((step, i) => (
        <section key={step.n} className="section" style={{ background: i % 2 === 1 ? 'var(--bg-surface)' : 'transparent' }}>
          <div className="container">
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 64,
              alignItems: 'center',
              direction: i % 2 === 1 ? 'rtl' : 'ltr',
            }}>
              {/* Text */}
              <RevealDiv style={{ direction: 'ltr' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
                  <StepNumber n={`0${step.n}`} color={step.color} />
                  <div>
                    <div style={{ fontSize: 12, color: step.color, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Step {step.n}</div>
                    <h2 style={{ fontSize: '1.9rem', margin: 0 }}>{step.title}</h2>
                  </div>
                </div>
                <p style={{ fontSize: 16, marginBottom: 24, color: 'var(--text-secondary)', fontStyle: 'italic' }}>{step.sub}</p>
                <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 24 }}>
                  {step.bullets.map(b => (
                    <li key={b} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 14 }}>
                      <CheckCircle2 size={16} color={step.color} style={{ flexShrink: 0, marginTop: 2 }} />
                      <span style={{ color: 'var(--text-primary)' }}>{b}</span>
                    </li>
                  ))}
                </ul>
                <p style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.7, padding: '14px 16px', background: `${step.color}08`, borderLeft: `3px solid ${step.color}40`, borderRadius: '0 var(--radius-sm) var(--radius-sm) 0' }}>
                  {step.detail}
                </p>
              </RevealDiv>

              {/* Visual card */}
              <RevealDiv delay={150} style={{ direction: 'ltr' }}>
                <div className="card" style={{
                  background: `linear-gradient(135deg,${step.color}0a,transparent)`,
                  border: `1px solid ${step.color}25`,
                  padding: 32,
                }}>
                  {/* Icon header */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 28 }}>
                    <div style={{ width: 56, height: 56, borderRadius: 16, background: `${step.color}18`, border: `1px solid ${step.color}30`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <step.icon size={26} color={step.color} />
                    </div>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 15 }}>{step.title}</div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 3 }}>Automated · Zero Config</div>
                    </div>
                  </div>

                  {/* Status items */}
                  {step.visual.map((v, vi) => (
                    <div key={v.label} style={{
                      display: 'flex', alignItems: 'center', gap: 12,
                      padding: '12px 14px', marginBottom: 10,
                      background: 'var(--bg-surface)', borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--border)',
                      animation: `fadeUp .5s ease forwards ${vi * 0.15}s`,
                    }}>
                      <div style={{ width: 32, height: 32, borderRadius: 8, background: `${v.color}15`, border: `1px solid ${v.color}25`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <v.icon size={14} color={v.color} />
                      </div>
                      <span style={{ flex: 1, fontSize: 14 }}>{v.label}</span>
                      <CheckCircle2 size={15} color="var(--success)" />
                    </div>
                  ))}

                  <div style={{ marginTop: 20, padding: '10px 14px', background: `${step.color}10`, borderRadius: 'var(--radius-sm)', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: step.color, animation: 'pulse-glow 2s infinite' }} />
                    <span style={{ fontSize: 12, color: step.color, fontWeight: 600 }}>Step {step.n} of 3 complete</span>
                  </div>
                </div>
              </RevealDiv>
            </div>
          </div>

          {/* Connector arrow */}
          {i < STEPS.length - 1 && (
            <div style={{ textAlign: 'center', marginTop: 48 }}>
              <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
                <div style={{ width: 1, height: 32, background: 'linear-gradient(to bottom,transparent,var(--border-glow))' }} />
                <ChevronRight size={20} color="var(--border-glow)" style={{ transform: 'rotate(90deg)' }} />
                <div style={{ width: 1, height: 32, background: 'linear-gradient(to bottom,var(--border-glow),transparent)' }} />
              </div>
            </div>
          )}
        </section>
      ))}

      {/* ── Real-time tracking deep-dive ─────────────────────── */}
      <section className="section" style={{ background: 'var(--bg-surface)' }}>
        <div className="container">
          <RevealDiv style={{ textAlign: 'center', marginBottom: 56 }}>
            <div className="badge badge-cyan" style={{ display: 'inline-flex', marginBottom: 16 }}>Real-Time Tracking</div>
            <h2>Every Click. Every Purchase.<br /><span className="gradient-text">Every Signal Captured.</span></h2>
            <p style={{ maxWidth: 520, margin: '16px auto 0' }}>
              Our weighted event system turns raw behavioural signals into personalization fuel —
              anonymously at first, then merged on login.
            </p>
          </RevealDiv>

          <div className="grid-4" style={{ marginBottom: 40 }}>
            {EVENT_WEIGHTS.map((e, i) => (
              <RevealDiv key={e.event} delay={i * 80}>
                <div className="card" style={{ textAlign: 'center', padding: 24 }}>
                  <div style={{ width: 48, height: 48, borderRadius: 12, background: `${e.color}15`, border: `1px solid ${e.color}25`, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 14px' }}>
                    <e.icon size={20} color={e.color} />
                  </div>
                  <code style={{ fontSize: 13, color: e.color, fontFamily: 'monospace', background: `${e.color}10`, padding: '2px 8px', borderRadius: 4 }}>{e.event}</code>
                  <div style={{ fontFamily: 'Outfit', fontWeight: 800, fontSize: '1.8rem', margin: '10px 0 4px', color: e.color }}>×{e.weight}</div>
                  <p style={{ fontSize: 12 }}>{e.desc}</p>
                </div>
              </RevealDiv>
            ))}
          </div>

          {/* Identity merging callout */}
          <RevealDiv>
            <div style={{ padding: '28px 32px', borderRadius: 'var(--radius-lg)', background: 'linear-gradient(135deg,rgba(59,130,246,.1),rgba(129,140,248,.08))', border: '1px solid rgba(59,130,246,.2)', display: 'flex', alignItems: 'flex-start', gap: 20 }}>
              <div style={{ width: 48, height: 48, borderRadius: 12, background: 'rgba(59,130,246,.15)', border: '1px solid rgba(59,130,246,.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <Server size={22} color="#3b82f6" />
              </div>
              <div>
                <h4 style={{ marginBottom: 8 }}>Deterministic Identity Merging</h4>
                <p style={{ fontSize: 14 }}>
                  Anonymous session events (pre-login) are automatically re-attributed to authenticated customers on login —
                  no fingerprinting, no heuristics. Historical browse, click, and cart behaviour instantly enriches the
                  customer's permanent recommendation profile.
                </p>
              </div>
            </div>
          </RevealDiv>
        </div>
      </section>

      {/* ── Architecture pipeline ─────────────────────────────── */}
      <section className="section">
        <div className="container">
          <RevealDiv style={{ textAlign: 'center', marginBottom: 56 }}>
            <div className="badge badge-blue" style={{ display: 'inline-flex', marginBottom: 16 }}>Under the Hood</div>
            <h2>The Full Pipeline at a Glance</h2>
          </RevealDiv>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0, flexWrap: 'wrap' }}>
            {[
              { label: 'Raw Data',     icon: Database,  color: '#3b82f6', sub: 'CSV / JSON / Parquet' },
              { label: 'AI Profiler',  icon: Cpu,       color: '#818cf8', sub: 'Auto schema mapping' },
              { label: '4 Models',     icon: Brain,     color: '#06b6d4', sub: 'Compete in parallel' },
              { label: 'Auto-Select',  icon: BarChart3, color: '#10b981', sub: 'Best NDCG@5 wins'    },
              { label: 'Live API',     icon: Globe,     color: '#f59e0b', sub: '<200ms responses'    },
            ].map((node, i) => (
              <div key={node.label} style={{ display: 'flex', alignItems: 'center' }}>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
                  <div style={{ width: 60, height: 60, borderRadius: 16, background: `${node.color}18`, border: `2px solid ${node.color}35`, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 0 24px ${node.color}20` }}>
                    <node.icon size={24} color={node.color} />
                  </div>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{node.label}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{node.sub}</div>
                  </div>
                </div>
                {i < 4 && (
                  <div style={{ display: 'flex', alignItems: 'center', padding: '0 12px', marginBottom: 24 }}>
                    <div style={{ width: 40, height: 1, background: 'var(--border-glow)' }} />
                    <ArrowRight size={14} color="var(--border-glow)" />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ──────────────────────────────────────────────── */}
      <section className="section-sm">
        <div className="container">
          <RevealDiv>
            <div style={{ textAlign: 'center', padding: '64px 40px', background: 'linear-gradient(135deg,rgba(59,130,246,.12),rgba(129,140,248,.1))', border: '1px solid rgba(59,130,246,.2)', borderRadius: 'var(--radius-xl)', position: 'relative', overflow: 'hidden' }}>
              <div className="orb orb-blue"   style={{ width: 300, height: 300, top: -80, right: -60 }} />
              <div className="orb orb-purple" style={{ width: 250, height: 250, bottom: -60, left: -40 }} />
              <div style={{ position: 'relative', zIndex: 1 }}>
                <h2 style={{ marginBottom: 14 }}>Ready to see it in action?</h2>
                <p style={{ marginBottom: 32, maxWidth: 420, margin: '0 auto 32px' }}>
                  Upload your dataset and watch the full pipeline run — from profiling to live recommendations.
                </p>
                <div style={{ display: 'flex', gap: 14, justifyContent: 'center', flexWrap: 'wrap' }}>
                  <Link to="/signup" className="btn btn-primary btn-lg">
                    Start for Free <ArrowRight size={17} />
                  </Link>
                  <Link to="/features" className="btn btn-secondary btn-lg">
                    See All Features
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
            <Link to="/features">Features</Link>
            <Link to="/signup">Get Started</Link>
            <Link to="/signin">Sign In</Link>
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>© 2026 AI_POD</div>
        </div>
      </footer>

      <style>{`
        @keyframes pulse-glow {
          0%,100%{box-shadow:0 0 0 0 rgba(59,130,246,.5)}
          50%{box-shadow:0 0 0 6px rgba(59,130,246,0)}
        }
        @keyframes fadeUp {
          from{opacity:0;transform:translateY(16px)}
          to{opacity:1;transform:translateY(0)}
        }
        @media (max-width: 768px) {
          [style*="gridTemplateColumns: '1fr 1fr'"] { grid-template-columns: 1fr !important; direction: ltr !important; }
        }
      `}</style>
    </div>
  );
}
