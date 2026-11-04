import { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { getDashboardModels, onboardTrain } from '../../api/client';
import { Brain, Trophy, RefreshCw, Database } from 'lucide-react';

export default function ModelStatus() {
  const navigate = useNavigate();
  const [data,     setData]     = useState(null);
  const [loading,  setLoading]  = useState(true);
  const [training, setTraining] = useState(false);
  const [error,    setError]    = useState('');

  const loadData = async () => {
    try {
      const res = await getDashboardModels();
      setData(res);
    } catch (err) {
      setError(err?.message || 'Failed to load model details');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleRetrain = async () => {
    setTraining(true);
    try {
      await onboardTrain();
    } catch {
      // Proceed to training view even if conflict or error
    }
    navigate('/onboarding/training');
  };

  const formatLastTrained = (ts) => {
    if (!ts) return 'Never trained';
    try {
      const d = new Date(ts);
      return d.toLocaleDateString(undefined, { month:'short', day:'numeric' }) + ' at ' + d.toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' });
    } catch {
      return ts;
    }
  };

  const winnerModel = data?.models?.find(m => m.is_winner);
  const isTrained = Boolean(winnerModel && data?.status === 'completed');

  return (
    <div>
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:32 }}>
        <div>
          <h3 style={{ marginBottom:8 }}>Model Status</h3>
          <p style={{ fontSize:14 }}>Full performance breakdown for the latest tournament run.</p>
        </div>
        <button className="btn btn-primary" onClick={handleRetrain} disabled={training}>
          {training ? <><RefreshCw size={15} className="animate-spin"/> Starting…</> : <><RefreshCw size={15}/> Retrain Model</>}
        </button>
      </div>

      {error && <div className="alert alert-error mb-6">{error}</div>}

      {/* Winner banner or Untrained placeholder */}
      {loading ? (
        <div className="card mb-8">
          <div className="skeleton" style={{ height:80 }}/>
        </div>
      ) : isTrained ? (
        <div style={{
          padding: 24,
          borderRadius: 'var(--radius-lg)',
          background: 'linear-gradient(135deg,rgba(16,185,129,.12),rgba(59,130,246,.08))',
          border: '2px solid rgba(16,185,129,.3)',
          marginBottom: 32,
          display: 'flex',
          alignItems: 'center',
          gap: 20,
        }}>
          <div style={{
            width:56, height:56, borderRadius:16,
            background:'rgba(245,158,11,.15)', border:'1px solid rgba(245,158,11,.3)',
            display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0,
          }}>
            <Trophy size={28} color="#f59e0b" fill="#f59e0b"/>
          </div>
          <div>
            <div style={{ fontSize:12, color:'var(--text-muted)', marginBottom:4 }}>Currently deployed winner</div>
            <div style={{ fontFamily:'Outfit', fontWeight:700, fontSize:'1.2rem', marginBottom:8 }}>
              {winnerModel.name}
            </div>
            <div style={{ display:'flex', gap:10, flexWrap:'wrap' }}>
              <span className="badge badge-green">
                NDCG@5: {winnerModel.ndcg != null ? Number(winnerModel.ndcg).toFixed(3) : '—'}
              </span>
              <span className="badge badge-blue">
                Precision@5: {winnerModel.precision != null ? Number(winnerModel.precision).toFixed(3) : '—'}
              </span>
              <span className="badge badge-purple">
                Recall@5: {winnerModel.recall != null ? Number(winnerModel.recall).toFixed(3) : '—'}
              </span>
            </div>
          </div>
          <div style={{ marginLeft:'auto', fontSize:12, color:'var(--text-muted)', textAlign:'right' }}>
            Last trained:<br/>
            <strong>{formatLastTrained(data?.last_trained)}</strong>
          </div>
        </div>
      ) : (
        <div className="card mb-8" style={{ border:'1px dashed var(--border-glow)', textAlign:'center', padding:32 }}>
          <Brain size={36} color="var(--accent-1)" style={{ opacity:0.6, marginBottom:12 }}/>
          <h4 style={{ marginBottom:6 }}>No Model Deployed Yet</h4>
          <p style={{ fontSize:13, color:'var(--text-muted)', maxWidth:440, margin:'0 auto 20px' }}>
            Upload your interaction data to train and automatically deploy the winning recommendation algorithm.
          </p>
          <Link to="/onboarding/upload" className="btn btn-primary btn-sm">
            Upload Dataset & Train
          </Link>
        </div>
      )}

      {/* All models comparison */}
      <div className="card mb-6">
        <h4 style={{ marginBottom:20 }}>All Models — Evaluation Leaderboard</h4>
        <div style={{ overflowX:'auto' }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:13 }}>
            <thead>
              <tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Model','NDCG@5','Precision@5','Recall@5','Status'].map(h => (
                  <th key={h} style={{ textAlign:'left', padding:'10px 12px', color:'var(--text-muted)', fontWeight:600 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5} style={{ padding:'24px', textAlign:'center', color:'var(--text-muted)' }}>
                    Loading leaderboard…
                  </td>
                </tr>
              ) : (data?.models || []).map(m => {
                const isWin = Boolean(m.is_winner);
                const color = m.color || '#3b82f6';
                let statusBadge = <span className="badge" style={{ opacity:0.6 }}>Not Started</span>;
                if (isWin) {
                  statusBadge = <span className="badge badge-green">✓ Deployed</span>;
                } else if (m.status === 'done') {
                  statusBadge = <span className="badge badge-purple">Evaluated</span>;
                } else if (m.status === 'failed') {
                  statusBadge = <span className="badge badge-red">Failed</span>;
                } else if (m.status === 'stalled') {
                  statusBadge = <span className="badge badge-yellow">Stalled</span>;
                } else if (m.status === 'training') {
                  statusBadge = <span className="badge badge-blue">Training…</span>;
                }

                return (
                  <tr key={m.id} style={{ borderBottom:'1px solid var(--border)', background: isWin ? `${color}08` : 'transparent' }}>
                    <td style={{ padding:'10px 12px' }}>
                      <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                        <div style={{ width:8, height:8, borderRadius:'50%', background:color, flexShrink:0 }}/>
                        <span style={{ fontWeight: isWin ? 600 : 400 }}>{m.name}</span>
                      </div>
                    </td>
                    <td style={{ padding:'10px 12px', fontWeight:600, color: isWin ? color : 'var(--text-primary)' }}>
                      {m.ndcg != null ? Number(m.ndcg).toFixed(3) : '—'}
                    </td>
                    <td style={{ padding:'10px 12px' }}>
                      {m.precision != null ? Number(m.precision).toFixed(3) : '—'}
                    </td>
                    <td style={{ padding:'10px 12px' }}>
                      {m.recall != null ? Number(m.recall).toFixed(3) : '—'}
                    </td>
                    <td style={{ padding:'10px 12px' }}>
                      {statusBadge}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Dataset Statistics */}
      <div className="card">
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:20 }}>
          <h4>Dataset Statistics</h4>
          <span style={{ fontSize:12, color:'var(--text-muted)' }}>From processed storage</span>
        </div>
        {loading ? (
          <div className="skeleton" style={{ height:60 }}/>
        ) : !data?.dataset_stats ? (
          <div style={{ textAlign:'center', padding:'20px', color:'var(--text-muted)' }}>
            <Database size={24} style={{ opacity:0.4, marginBottom:8 }}/>
            <p style={{ fontSize:13, margin:0 }}>No processed dataset found for this tenant.</p>
          </div>
        ) : (
          <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:24 }}>
            {[
              {
                label: 'Customers',
                val: data.dataset_stats.customers,
                minReq: 50,
              },
              {
                label: 'Products',
                val: data.dataset_stats.products,
                minReq: 1,
              },
              {
                label: 'Interactions',
                val: data.dataset_stats.interactions,
                minReq: 200,
              },
            ].map(s => {
              const count = s.val ?? 0;
              const pct = s.val != null ? Math.min(100, Math.max(10, Math.round((count / (s.minReq * 5)) * 100))) : 0;
              return (
                <div key={s.label}>
                  <div style={{ display:'flex', justifyContent:'space-between', marginBottom:6 }}>
                    <span style={{ fontSize:13, color:'var(--text-secondary)' }}>{s.label}</span>
                    <span style={{ fontWeight:600, fontSize:13 }}>
                      {s.val != null ? s.val.toLocaleString() : '—'}
                    </span>
                  </div>
                  <div style={{ height:6, background:'var(--border)', borderRadius:99, overflow:'hidden' }}>
                    <div style={{ height:'100%', width:`${pct}%`, background:'var(--accent-grad)', borderRadius:99, maxWidth:'100%' }}/>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
