import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { onboardTrain, onboardStatus } from '../../api/client';
import { ArrowRight, Trophy, Brain, RefreshCw, AlertTriangle } from 'lucide-react';

const MODELS = [
  { id: 'content',       label: 'Content-Based',          sub: 'Profile Cosine Similarity',   color: '#3b82f6' },
  { id: 'collaborative', label: 'Collaborative Filtering', sub: 'TruncatedSVD Latent Space',   color: '#818cf8' },
  { id: 'hybrid',        label: 'Dynamic Hybrid',          sub: 'Rank Blend Ensemble',          color: '#06b6d4' },
  { id: 'xgboost',       label: 'Learned Ranking',         sub: 'XGBoost Classifier',           color: '#10b981' },
];

export default function TrainingStep() {
  const navigate = useNavigate();

  const [status,    setStatus]    = useState('not_started');
  const [winner,    setWinner]    = useState(null);
  const [winnerKey, setWinnerKey] = useState(null);
  const [metrics,   setMetrics]   = useState({});
  const [modelSt,   setModelSt]   = useState({
    content: 'queued',
    collaborative: 'queued',
    hybrid: 'queued',
    xgboost: 'queued',
  });
  const [started,   setStarted]   = useState(false);
  const [error,     setError]     = useState('');
  const pollRef = useRef(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const applyStatusData = (d) => {
    if (d.status) setStatus(d.status);
    if (d.models) setModelSt(d.models);
    if (d.winner_model) setWinner(d.winner_model);
    if (d.winner_key) setWinnerKey(d.winner_key);
    if (d.metrics) setMetrics(d.metrics);
    if (d.error) setError(d.error);

    if (['completed', 'complete', 'failed', 'stalled'].includes(d.status)) {
      stopPolling();
    }
  };

  const pollStatus = async () => {
    try {
      const d = await onboardStatus();
      applyStatusData(d);
    } catch (err) {
      console.warn('Status poll error:', err);
    }
  };

  // Inspect existing status on mount
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const d = await onboardStatus();
        if (!mounted) return;
        applyStatusData(d);

        if (['queued', 'running'].includes(d.status)) {
          setStarted(true);
          stopPolling();
          pollRef.current = setInterval(pollStatus, 2500);
        } else if (['completed', 'complete'].includes(d.status)) {
          setStarted(true);
        }
      } catch (err) {
        console.warn('Initial status fetch error:', err);
      }
    })();

    return () => {
      mounted = false;
      stopPolling();
    };
  }, []);

  const startTraining = async () => {
    setStarted(true);
    setError('');
    setStatus('running');
    try {
      await onboardTrain();
      stopPolling();
      pollRef.current = setInterval(pollStatus, 2500);
    } catch (err) {
      setError(err?.detail || err?.message || 'Failed to start training.');
      setStatus('failed');
      stopPolling();
    }
  };

  const ModelCard = ({ model }) => {
    const st = modelSt[model.id] || 'queued';
    const isDone = st === 'done';
    const isWin = (winnerKey && winnerKey === model.id) ||
      (winner && winner.toLowerCase().includes(model.id === 'xgboost' ? 'xgboost' : model.id === 'content' ? 'content' : model.id));
    const modelMetrics = metrics[model.id];

    return (
      <div style={{
        padding: 20,
        borderRadius: 'var(--radius-lg)',
        border: `2px solid ${isWin ? model.color : isDone ? `${model.color}44` : 'var(--border)'}`,
        background: isWin ? `${model.color}12` : 'var(--bg-card)',
        transition: 'all .4s',
        position: 'relative',
        overflow: 'hidden',
      }}>
        {isWin && (
          <div style={{ position: 'absolute', top: 10, right: 10 }}>
            <Trophy size={20} color="#f59e0b" fill="#f59e0b"/>
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
          <div style={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            background: st === 'failed' ? '#ef4444' : model.color,
            animation: st === 'training' || st === 'evaluating' ? 'pulse-glow 1.5s infinite' : undefined,
          }}/>
          <span style={{ fontWeight: 600, fontSize: 14 }}>{model.label}</span>
          <span
            className={`badge ${
              st === 'done'
                ? 'badge-green'
                : st === 'training'
                ? 'badge-blue'
                : st === 'evaluating'
                ? 'badge-yellow'
                : st === 'failed'
                ? 'badge-red'
                : 'badge-purple'
            }`}
            style={{ marginLeft: 'auto', fontSize: 11 }}
          >
            {st}
          </span>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>{model.sub}</div>
        {/* Progress bar */}
        <div style={{ height: 3, background: 'var(--border)', borderRadius: 99, overflow: 'hidden' }}>
          <div style={{
            height: '100%',
            borderRadius: 99,
            background: st === 'failed' ? '#ef4444' : model.color,
            width: st === 'queued' ? '0%' : st === 'training' ? '40%' : st === 'evaluating' ? '80%' : '100%',
            transition: 'width 0.6s ease',
          }}/>
        </div>
        {isDone && modelMetrics?.ndcg !== undefined && (
          <div style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <span className="badge badge-green">NDCG@5: {Number(modelMetrics.ndcg).toFixed(3)}</span>
            {modelMetrics.precision !== undefined && (
              <span className="badge badge-blue">P@5: {Number(modelMetrics.precision).toFixed(3)}</span>
            )}
          </div>
        )}
      </div>
    );
  };

  const isComplete = ['completed', 'complete'].includes(status) || Boolean(winner);
  const isFailed = status === 'failed' || status === 'stalled';
  const winnerMetrics = (winnerKey && metrics[winnerKey]) || (metrics.ndcg ? metrics : null);

  return (
    <div className="container-md">
      <div style={{ textAlign: 'center', marginBottom: 40 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12, marginBottom: 16 }}>
          <Brain size={28} color="var(--accent-1)"/>
          <h2>Model Training Arena</h2>
        </div>
        <p>
          {isComplete
            ? 'Training complete! A winner has been selected.'
            : isFailed
            ? 'Training encountered an error.'
            : started
            ? '4 models are competing on your data…'
            : 'Start training to let 4 AI models compete on your dataset.'}
        </p>
      </div>

      {/* Model cards grid */}
      <div className="grid-2" style={{ marginBottom: 32 }}>
        {MODELS.map(m => <ModelCard key={m.id} model={m} />)}
      </div>

      {/* Status Alert */}
      {started && !isComplete && !isFailed && (
        <div className="alert alert-info mb-6">
          <RefreshCw size={16} className="animate-spin"/> Training in progress… This usually takes 1–3 minutes.
        </div>
      )}

      {/* Failure State */}
      {isFailed && (
        <div className="alert alert-error mb-6" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <AlertTriangle size={18} color="#ef4444"/>
            <span>{error || (status === 'stalled' ? 'Training job stalled after 15 minutes.' : 'Training failed.')}</span>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={startTraining}>
            Retry Training
          </button>
        </div>
      )}

      {/* Winner Banner */}
      {isComplete && winner && (
        <div style={{
          padding: 24,
          borderRadius: 'var(--radius-lg)',
          background: 'linear-gradient(135deg,rgba(245,158,11,.12),rgba(16,185,129,.1))',
          border: '2px solid rgba(245,158,11,.4)',
          textAlign: 'center',
          marginBottom: 24,
          animation: 'fadeUp .6s ease',
        }}>
          <Trophy size={36} color="#f59e0b" fill="#f59e0b" style={{ margin: '0 auto 12px' }}/>
          <h3 style={{ marginBottom: 8 }}>🎉 Winner Selected!</h3>
          <h4 style={{ color: '#f59e0b', marginBottom: 16 }}>{winner}</h4>
          {winnerMetrics && (
            <div style={{ display: 'flex', justifyContent: 'center', gap: 12, flexWrap: 'wrap' }}>
              {winnerMetrics.ndcg !== undefined && (
                <span className="badge badge-green">NDCG@5: {Number(winnerMetrics.ndcg).toFixed(3)}</span>
              )}
              {winnerMetrics.precision !== undefined && (
                <span className="badge badge-blue">Precision@5: {Number(winnerMetrics.precision).toFixed(3)}</span>
              )}
              {winnerMetrics.recall !== undefined && (
                <span className="badge badge-purple">Recall@5: {Number(winnerMetrics.recall).toFixed(3)}</span>
              )}
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: isComplete ? 'flex-end' : 'center' }}>
        {!started ? (
          <button className="btn btn-primary btn-lg" onClick={startTraining}>
            <Brain size={18}/> Start Training
          </button>
        ) : isComplete ? (
          <button className="btn btn-primary" onClick={() => navigate('/onboarding/integrate')}>
            View Integration Guide <ArrowRight size={16}/>
          </button>
        ) : isFailed ? (
          <button className="btn btn-primary" onClick={startTraining}>
            <RefreshCw size={16}/> Retry Training
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
