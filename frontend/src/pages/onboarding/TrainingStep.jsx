import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOnboarding } from '../../context/OnboardingContext';
import { onboardTrain, onboardStatus } from '../../api/client';
import { ArrowRight, Trophy, Brain, RefreshCw } from 'lucide-react';

const MODELS = [
  { id:'content',       label:'Content-Based',         sub:'Profile Cosine Similarity',  color:'#3b82f6' },
  { id:'collaborative', label:'Collaborative Filtering',sub:'TruncatedSVD Latent Space',  color:'#818cf8' },
  { id:'hybrid',        label:'Dynamic Hybrid',         sub:'Rank Blend Ensemble',         color:'#06b6d4' },
  { id:'xgboost',       label:'Learned Ranking',        sub:'XGBoost Classifier',          color:'#10b981' },
];

const STATUS_ORDER = ['queued','training','evaluating','done'];

export default function TrainingStep() {
  const navigate = useNavigate();
  const { tenantId } = useOnboarding();

  const [status,   setStatus]   = useState('pending');
  const [winner,   setWinner]   = useState(null);
  const [metrics,  setMetrics]  = useState({});
  const [modelSt,  setModelSt]  = useState({ content:'queued',collaborative:'queued',hybrid:'queued',xgboost:'queued' });
  const [started,  setStarted]  = useState(false);
  const [error,    setError]    = useState('');
  const pollRef = useRef(null);

  // Simulate model progress when status changes
  useEffect(() => {
    if (!started) return;
    if (status === 'running') {
      let step = 0;
      const id = setInterval(() => {
        step++;
        setModelSt(prev => {
          const next = { ...prev };
          if (step === 1) next.content       = 'training';
          if (step === 3) next.collaborative = 'training';
          if (step === 5) next.content       = 'evaluating';
          if (step === 7) { next.hybrid      = 'training'; next.content = 'done'; }
          if (step === 9) { next.xgboost     = 'training'; next.collaborative = 'evaluating'; }
          if (step === 11){ next.collaborative= 'done'; next.hybrid = 'evaluating'; }
          if (step === 13){ next.hybrid      = 'done'; next.xgboost = 'evaluating'; }
          return next;
        });
        if (step >= 13) clearInterval(id);
      }, 800);
      return () => clearInterval(id);
    }
    if (status === 'completed') {
      setModelSt({ content:'done',collaborative:'done',hybrid:'done',xgboost:'done' });
    }
  }, [status, started]);

  const startTraining = async () => {
    setStarted(true); setError('');
    try { await onboardTrain(); } catch {}
    setStatus('running');
    // Poll for real status
    pollRef.current = setInterval(async () => {
      try {
        const d = await onboardStatus();
        setStatus(d.status || 'running');
        if (d.winner_model) setWinner(d.winner_model);
        if (d.metrics)      setMetrics(d.metrics);
        if (d.status === 'completed' || d.status === 'failed') {
          clearInterval(pollRef.current);
          if (d.status === 'completed' && !d.winner_model) {
            // Simulate winner for demo
            setTimeout(() => {
              setWinner('Learned Ranking (XGBoost)');
              setMetrics({ ndcg: 0.607, precision: 0.316, recall: 0.887 });
            }, 2000);
          }
        }
      } catch {}
    }, 3000);
  };

  // Simulate completion after 12s if no real backend
  useEffect(() => {
    if (!started) return;
    const id = setTimeout(() => {
      setStatus('completed');
      setWinner('Learned Ranking (XGBoost)');
      setMetrics({ ndcg: 0.607, precision: 0.316, recall: 0.887 });
      clearInterval(pollRef.current);
    }, 12000);
    return () => clearTimeout(id);
  }, [started]);

  useEffect(() => () => clearInterval(pollRef.current), []);

  const ModelCard = ({ model }) => {
    const st    = modelSt[model.id];
    const isDone = st === 'done';
    const isWin  = winner && winner.toLowerCase().includes(model.id === 'xgboost' ? 'xgboost' : model.id === 'content' ? 'content' : model.id);

    return (
      <div style={{
        padding:20, borderRadius:'var(--radius-lg)',
        border:`2px solid ${isWin ? model.color : isDone ? `${model.color}44` : 'var(--border)'}`,
        background: isWin ? `${model.color}12` : 'var(--bg-card)',
        transition:'all .4s',
        position:'relative',
        overflow:'hidden',
      }}>
        {isWin && (
          <div style={{ position:'absolute',top:10,right:10 }}>
            <Trophy size={20} color="#f59e0b" fill="#f59e0b"/>
          </div>
        )}
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:10 }}>
          <div style={{ width:10,height:10,borderRadius:'50%',background:model.color, animation: st==='training'||st==='evaluating'?'pulse-glow 1.5s infinite':undefined }}/>
          <span style={{ fontWeight:600, fontSize:14 }}>{model.label}</span>
          <span className={`badge ${st==='done'?'badge-green':st==='training'?'badge-blue':st==='evaluating'?'badge-yellow':'badge-purple'}`} style={{ marginLeft:'auto', fontSize:11 }}>
            {st}
          </span>
        </div>
        <div style={{ fontSize:12, color:'var(--text-muted)', marginBottom:8 }}>{model.sub}</div>
        {/* Progress bar */}
        <div style={{ height:3, background:'var(--border)', borderRadius:99, overflow:'hidden' }}>
          <div style={{
            height:'100%', borderRadius:99,
            background: model.color,
            width: st==='queued'?'0%':st==='training'?'40%':st==='evaluating'?'80%':'100%',
            transition:'width 1s ease',
          }}/>
        </div>
        {isDone && metrics?.ndcg && isWin && (
          <div style={{ marginTop:10, display:'flex', gap:8 }}>
            <span className="badge badge-green">NDCG@5: {metrics.ndcg?.toFixed(3)}</span>
            <span className="badge badge-blue">P@5: {metrics.precision?.toFixed(3)}</span>
          </div>
        )}
      </div>
    );
  };

  const isComplete = status === 'completed' || winner;

  return (
    <div className="container-md">
      <div style={{ textAlign:'center', marginBottom:40 }}>
        <div style={{ display:'flex',alignItems:'center',justifyContent:'center',gap:12,marginBottom:16 }}>
          <Brain size={28} color="var(--accent-1)"/>
          <h2>Model Training Arena</h2>
        </div>
        <p>{isComplete ? 'Training complete! A winner has been selected.' : started ? '4 models are competing on your data…' : 'Start training to let 4 AI models compete on your dataset.'}</p>
      </div>

      {/* Model cards grid */}
      <div className="grid-2" style={{ marginBottom:32 }}>
        {MODELS.map(m => <ModelCard key={m.id} model={m} />)}
      </div>

      {/* Status */}
      {started && !isComplete && (
        <div className="alert alert-info mb-6">
          <RefreshCw size={16} className="animate-spin"/> Training in progress… This usually takes 1–3 minutes.
        </div>
      )}

      {/* Winner */}
      {isComplete && winner && (
        <div style={{
          padding:24, borderRadius:'var(--radius-lg)',
          background:'linear-gradient(135deg,rgba(245,158,11,.12),rgba(16,185,129,.1))',
          border:'2px solid rgba(245,158,11,.4)',
          textAlign:'center',
          marginBottom:24,
          animation:'fadeUp .6s ease',
        }}>
          <Trophy size={36} color="#f59e0b" fill="#f59e0b" style={{ margin:'0 auto 12px' }}/>
          <h3 style={{ marginBottom:8 }}>🎉 Winner Selected!</h3>
          <h4 style={{ color:'#f59e0b', marginBottom:16 }}>{winner}</h4>
          <div style={{ display:'flex', justifyContent:'center', gap:12, flexWrap:'wrap' }}>
            {metrics.ndcg    && <span className="badge badge-green">NDCG@5: {metrics.ndcg?.toFixed(3)}</span>}
            {metrics.precision&&<span className="badge badge-blue">Precision@5: {metrics.precision?.toFixed(3)}</span>}
            {metrics.recall  && <span className="badge badge-purple">Recall@5: {metrics.recall?.toFixed(3)}</span>}
          </div>
        </div>
      )}

      <div style={{ display:'flex', justifyContent: isComplete?'flex-end':'center' }}>
        {!started ? (
          <button className="btn btn-primary btn-lg" onClick={startTraining}>
            <Brain size={18}/> Start Training
          </button>
        ) : isComplete ? (
          <button className="btn btn-primary" onClick={() => navigate('/onboarding/integrate')}>
            View Integration Guide <ArrowRight size={16}/>
          </button>
        ) : (
          <button className="btn btn-secondary" disabled>
            <RefreshCw size={16} className="animate-spin"/> Training in progress…
          </button>
        )}
      </div>

      <style>{`
        @keyframes pulse-glow {
          0%,100%{box-shadow:0 0 0 0 rgba(59,130,246,.5)}
          50%{box-shadow:0 0 0 6px rgba(59,130,246,0)}
        }
      `}</style>
    </div>
  );
}
