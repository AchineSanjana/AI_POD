import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import Navbar from '../components/Navbar';
import {
  Zap, Upload, Brain, Code2, ArrowRight, CheckCircle2,
  BarChart3, ShieldCheck, Rocket, Globe, Star, ChevronRight,
} from 'lucide-react';

/* ── Animated Counter ───────────────────────────────────────── */
function Counter({ end, suffix = '', decimals = 0 }) {
  const [val, setVal] = useState(0);
  const ref = useRef(null);

  useEffect(() => {
    const observer = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      observer.disconnect();
      let start = 0;
      const step = end / 60;
      const id = setInterval(() => {
        start += step;
        if (start >= end) { setVal(end); clearInterval(id); }
        else setVal(start);
      }, 16);
    });
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [end]);

  return (
    <span ref={ref}>
      {decimals > 0 ? val.toFixed(decimals) : Math.floor(val)}{suffix}
    </span>
  );
}

/* ── Feature Card ───────────────────────────────────────────── */
function FeatureCard({ icon: Icon, title, desc, color }) {
  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ width: 48, height: 48, borderRadius: 12, background: `${color}1a`, border: `1px solid ${color}33`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Icon size={22} color={color} />
      </div>
      <div>
        <h4 style={{ marginBottom: 8 }}>{title}</h4>
        <p style={{ fontSize: 14 }}>{desc}</p>
      </div>
    </div>
  );
}

/* ── Industry Demo Card ─────────────────────────────────────── */
function IndustryCard({ emoji, label, desc, color }) {
  return (
    <div className="card" style={{ textAlign: 'center', cursor: 'pointer', background: `linear-gradient(135deg,${color}10,transparent)` }}>
      <div style={{ fontSize: 40, marginBottom: 12 }}>{emoji}</div>
      <h4 style={{ marginBottom: 6 }}>{label}</h4>
      <p style={{ fontSize: 13 }}>{desc}</p>
    </div>
  );
}

export default function Landing() {
  return (
    <div style={{ overflow: 'hidden' }}>
      <Navbar />

      {/* ── Hero ─────────────────────────────────────────────── */}
      <section style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', position: 'relative', paddingTop: 100 }}>
        {/* Orbs */}
        <div className="orb orb-blue"  style={{ width: 500, height: 500, top: -100, right: -100, opacity: .6 }} />
        <div className="orb orb-purple"style={{ width: 400, height: 400, bottom: 0, left: -100,  opacity: .5 }} />
        <div className="orb orb-cyan"  style={{ width: 300, height: 300, top: '40%', left: '40%', opacity: .3 }} />

        <div className="container text-center" style={{ position: 'relative', zIndex: 1 }}>
          <div className="animate-fade-up">
            <div className="badge badge-blue" style={{ margin: '0 auto 24px', display: 'inline-flex' }}>
              <Zap size={12} /> AI-Powered Recommendations — Zero Code Required
            </div>
          </div>

          <h1 className="animate-fade-up" style={{ animationDelay: '.1s', maxWidth: 800, margin: '0 auto 24px' }}>
            The Smartest{' '}
            <span className="gradient-text">Recommendation Engine</span>{' '}
            for Any Business
          </h1>

          <p className="animate-fade-up" style={{ animationDelay: '.2s', maxWidth: 560, margin: '0 auto 40px', fontSize: 18 }}>
            Upload your data. Watch 4 AI models compete. Embed personalized recommendations in under 10 minutes — no ML expertise needed.
          </p>

          <div className="animate-fade-up" style={{ animationDelay: '.3s', display: 'flex', gap: 16, justifyContent: 'center', flexWrap: 'wrap' }}>
            <Link to="/signup" className="btn btn-primary btn-lg">
              Get Started Free <ArrowRight size={18} />
            </Link>
            <Link to="/signin" className="btn btn-secondary btn-lg">
              Sign In
            </Link>
          </div>

          {/* Live demo chip */}
          <div className="animate-fade-up" style={{ animationDelay: '.4s', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 40, color: 'var(--text-muted)', fontSize: 13 }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--success)', animation: 'pulse-glow 2s infinite' }} />
            Live on production · No credit card required
          </div>
        </div>
      </section>

      {/* ── Metrics Bar ──────────────────────────────────────── */}
      <section style={{ borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)', padding: '40px 0', background: 'var(--bg-surface)' }}>
        <div className="container">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 32, textAlign: 'center' }}>
            {[
              { label: 'NDCG@5 Score',      val: 0.95, suf: '', dec: 2 },
              { label: 'SDK Bundle Size',   val: 25,   suf: 'KB', dec: 0 },
              { label: 'API Response',      val: 200,  suf: 'ms', dec: 0 },
              { label: 'Models Competing',  val: 4,    suf: '',   dec: 0 },
            ].map(m => (
              <div key={m.label}>
                <div style={{ fontFamily: 'Outfit', fontWeight: 800, fontSize: '2.2rem', background: 'linear-gradient(135deg,#3b82f6,#818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                  <Counter end={m.val} suffix={m.suf} decimals={m.dec} />
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: 13, marginTop: 4 }}>{m.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How It Works ─────────────────────────────────────── */}
      <section className="section" id="how-it-works">
        <div className="container">
          <div className="text-center mb-8">
            <div className="badge badge-purple" style={{ margin: '0 auto 16px', display: 'inline-flex' }}>How It Works</div>
            <h2>From Data to Recommendations<br /><span className="gradient-text">in 3 Simple Steps</span></h2>
          </div>
          <div className="grid-3" style={{ position: 'relative' }}>
            {[
              { n: '01', icon: Upload, color: '#3b82f6', title: 'Upload Your Data', desc: 'Drop in your CSV, Parquet, or JSON. Our AI profiles your schema and auto-detects columns — zero configuration needed.' },
              { n: '02', icon: Brain,  color: '#818cf8', title: 'AI Trains 4 Models', desc: '4 algorithms compete in real-time: Content-Based, Collaborative Filtering, Hybrid, and XGBoost Learned Ranking.' },
              { n: '03', icon: Code2,  color: '#06b6d4', title: 'Embed & Personalize', desc: 'Copy a single script tag. Recommendations go live instantly on any website, Shopify store, or web app.' },
            ].map(s => (
              <div key={s.n} className="card" style={{ position: 'relative', overflow: 'hidden' }}>
                <div style={{ position: 'absolute', top: 16, right: 16, fontFamily: 'Outfit', fontWeight: 800, fontSize: 48, color: `${s.color}15`, lineHeight: 1 }}>{s.n}</div>
                <div style={{ width: 52, height: 52, borderRadius: 14, background: `${s.color}20`, border: `1px solid ${s.color}30`, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
                  <s.icon size={24} color={s.color} />
                </div>
                <h4 style={{ marginBottom: 10 }}>{s.title}</h4>
                <p style={{ fontSize: 14 }}>{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features ─────────────────────────────────────────── */}
      <section className="section-sm" id="features" style={{ background: 'var(--bg-surface)' }}>
        <div className="container">
          <div className="text-center mb-8">
            <div className="badge badge-cyan" style={{ margin: '0 auto 16px', display: 'inline-flex' }}>Features</div>
            <h2>Everything You Need to<br /><span className="gradient-text">Personalize at Scale</span></h2>
          </div>
          <div className="grid-3">
            <FeatureCard icon={Brain}      color="#818cf8" title="Domain-Agnostic AI"         desc="Works out of the box for E-commerce, Telecom, Grocery, Fashion, SaaS, and more — zero custom code." />
            <FeatureCard icon={BarChart3}  color="#3b82f6" title="Autonomous Model Selection" desc="4 algorithms compete on your data. The best NDCG@5 winner is automatically deployed." />
            <FeatureCard icon={Zap}        color="#06b6d4" title="Real-Time Tracking"         desc="Captures views, clicks, carts, and purchases via 25KB SDK with seamless identity merging." />
            <FeatureCard icon={ShieldCheck}color="#10b981" title="Multi-Tenant Isolation"     desc="Complete data isolation per tenant. Your customers' data never touches another tenant's pipeline." />
            <FeatureCard icon={Rocket}     color="#f59e0b" title="Zero-Code Onboarding"       desc="AI profiler auto-detects schema, generates config, and starts training — no ML expertise required." />
            <FeatureCard icon={Globe}      color="#ef4444" title="Shopify & AWS Native"        desc="One-click Shopify OAuth integration. S3 and SQS support for cloud-scale deployments." />
          </div>
        </div>
      </section>

      {/* ── Industry Demos ────────────────────────────────────── */}
      <section className="section">
        <div className="container">
          <div className="text-center mb-8">
            <h2>Works Across <span className="gradient-text">Every Industry</span></h2>
            <p style={{ marginTop: 12, maxWidth: 500, margin: '12px auto 0' }}>One platform. Zero code changes. Proven across 5 different verticals.</p>
          </div>
          <div className="grid-4">
            <IndustryCard emoji="🛒" label="E-Commerce"   color="#3b82f6" desc="Product recommendations and cart upsells" />
            <IndustryCard emoji="🥦" label="Grocery"       color="#10b981" desc="Smart repeat orders and basket building" />
            <IndustryCard emoji="👗" label="Fashion"       color="#818cf8" desc="Style personalization and outfit suggestions" />
            <IndustryCard emoji="📡" label="Telecom"       color="#06b6d4" desc="Add-on package recommendations by tenure" />
          </div>
        </div>
      </section>

      {/* ── CTA Banner ───────────────────────────────────────── */}
      <section className="section-sm">
        <div className="container">
          <div style={{
            background: 'linear-gradient(135deg,rgba(59,130,246,.15),rgba(129,140,248,.15))',
            border: '1px solid rgba(59,130,246,.25)',
            borderRadius: 'var(--radius-xl)',
            padding: '64px 48px',
            textAlign: 'center',
            position: 'relative',
            overflow: 'hidden',
          }}>
            <div className="orb orb-blue"   style={{ width: 300, height: 300, top: -100, right: -50 }} />
            <div className="orb orb-purple" style={{ width: 250, height: 250, bottom: -80, left: -50 }} />
            <div style={{ position: 'relative', zIndex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, marginBottom: 16 }}>
                {[1,2,3,4,5].map(i => <Star key={i} size={18} color="#f59e0b" fill="#f59e0b" />)}
              </div>
              <h2 style={{ marginBottom: 16 }}>Start recommending in<br /><span className="gradient-text">under 10 minutes</span></h2>
              <p style={{ marginBottom: 32, maxWidth: 480, margin: '0 auto 32px' }}>Join businesses using AI_POD to deliver personalized experiences that drive revenue.</p>
              <Link to="/signup" className="btn btn-primary btn-lg">
                Create Free Account <ArrowRight size={18} />
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────────── */}
      <footer style={{ borderTop: '1px solid var(--border)', padding: '40px 0' }}>
        <div className="container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 30, height: 30, borderRadius: 8, background: 'linear-gradient(135deg,#3b82f6,#818cf8)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Zap size={14} color="#fff" />
            </div>
            <span style={{ fontFamily: 'Outfit', fontWeight: 700 }}>AI_POD</span>
          </div>
          <div style={{ display: 'flex', gap: 24, color: 'var(--text-muted)', fontSize: 13 }}>
            <Link to="/signup">Get Started</Link>
            <Link to="/signin">Sign In</Link>
            <a href="#features">Features</a>
          </div>
          <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>© 2026 AI_POD. All rights reserved.</div>
        </div>
      </footer>
    </div>
  );
}
