import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { onboardTrain } from '../../api/client';
import { Brain, Trophy, RefreshCw, ArrowRight } from 'lucide-react';

const MODELS_DATA = [
  { name:'Content-Based (Profile Cosine)', ndcg:0.421, precision:0.198, recall:0.712, id:'content',       color:'#3b82f6' },
  { name:'Collaborative Filtering (SVD)',  ndcg:0.389, precision:0.175, recall:0.680, id:'collaborative', color:'#818cf8' },
  { name:'Dynamic Hybrid Ensemble',        ndcg:0.451, precision:0.218, recall:0.740, id:'hybrid',        color:'#06b6d4' },
  { name:'Learned Ranking (XGBoost)',      ndcg:0.607, precision:0.316, recall:0.887, id:'xgboost',       color:'#10b981' },
];

export default function ModelStatus() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);

  const winner = MODELS_DATA.reduce((a,b) => a.ndcg > b.ndcg ? a : b);

  const handleRetrain = async () => {
    setLoading(true);
    try { await onboardTrain(); } catch {}
    navigate('/onboarding/training');
  };

  return (
    <div>
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:32 }}>
        <div>
          <h3 style={{ marginBottom:8 }}>Model Status</h3>
          <p style={{ fontSize:14 }}>Full performance breakdown for the last training run.</p>
        </div>
        <button className="btn btn-primary" onClick={handleRetrain} disabled={loading}>
          {loading ? <><RefreshCw size={15} className="animate-spin"/> Starting…</> : <><RefreshCw size={15}/> Retrain Model</>}
        </button>
      </div>

      {/* Winner banner */}
      <div style={{ padding:24, borderRadius:'var(--radius-lg)', background:'linear-gradient(135deg,rgba(16,185,129,.12),rgba(59,130,246,.08))', border:'2px solid rgba(16,185,129,.3)', marginBottom:32, display:'flex', alignItems:'center', gap:20 }}>
        <div style={{ width:56,height:56,borderRadius:16,background:'rgba(245,158,11,.15)',border:'1px solid rgba(245,158,11,.3)',display:'flex',alignItems:'center',justifyContent:'center',flexShrink:0 }}>
          <Trophy size={28} color="#f59e0b" fill="#f59e0b"/>
        </div>
        <div>
          <div style={{ fontSize:12, color:'var(--text-muted)', marginBottom:4 }}>Currently deployed winner</div>
          <div style={{ fontFamily:'Outfit', fontWeight:700, fontSize:'1.2rem', marginBottom:8 }}>{winner.name}</div>
          <div style={{ display:'flex', gap:10 }}>
            <span className="badge badge-green">NDCG@5: {winner.ndcg}</span>
            <span className="badge badge-blue">Precision@5: {winner.precision}</span>
            <span className="badge badge-purple">Recall@5: {winner.recall}</span>
          </div>
        </div>
        <div style={{ marginLeft:'auto', fontSize:12, color:'var(--text-muted)' }}>
          Last trained:<br/><strong>Today, 09:14</strong>
        </div>
      </div>

      {/* All models comparison */}
      <div className="card mb-6">
        <h4 style={{ marginBottom:20 }}>All Models — Last Evaluation</h4>
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
              {[...MODELS_DATA].sort((a,b)=>b.ndcg-a.ndcg).map(m => (
                <tr key={m.id} style={{ borderBottom:'1px solid var(--border)', background: m.id===winner.id?`${m.color}08`:'transparent' }}>
                  <td style={{ padding:'10px 12px' }}>
                    <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                      <div style={{ width:8,height:8,borderRadius:'50%',background:m.color,flexShrink:0 }}/>
                      <span style={{ fontWeight: m.id===winner.id ? 600 : 400 }}>{m.name}</span>
                    </div>
                  </td>
                  <td style={{ padding:'10px 12px', fontWeight:600, color:m.id===winner.id?m.color:'var(--text-primary)' }}>{m.ndcg}</td>
                  <td style={{ padding:'10px 12px' }}>{m.precision}</td>
                  <td style={{ padding:'10px 12px' }}>{m.recall}</td>
                  <td style={{ padding:'10px 12px' }}>
                    {m.id===winner.id
                      ? <span className="badge badge-green">✓ Deployed</span>
                      : <span className="badge badge-purple">Evaluated</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Metric bars */}
      <div className="card">
        <h4 style={{ marginBottom:20 }}>Dataset Statistics</h4>
        <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:24 }}>
          {[
            { label:'Customers',    val:7043,   max:10000 },
            { label:'Products',     val:10,     max:50    },
            { label:'Interactions', val:20381,  max:50000 },
          ].map(s => (
            <div key={s.label}>
              <div style={{ display:'flex', justifyContent:'space-between', marginBottom:6 }}>
                <span style={{ fontSize:13, color:'var(--text-secondary)' }}>{s.label}</span>
                <span style={{ fontWeight:600, fontSize:13 }}>{s.val.toLocaleString()}</span>
              </div>
              <div style={{ height:6, background:'var(--border)', borderRadius:99, overflow:'hidden' }}>
                <div style={{ height:'100%', width:`${(s.val/s.max)*100}%`, background:'var(--accent-grad)', borderRadius:99, maxWidth:'100%' }}/>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
