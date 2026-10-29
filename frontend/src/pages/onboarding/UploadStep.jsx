import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOnboarding } from '../../context/OnboardingContext';
import { onboardUpload } from '../../api/client';
import { Upload, FileText, Table, ArrowRight, AlertCircle } from 'lucide-react';

export default function UploadStep() {
  const navigate = useNavigate();
  const { setProfile } = useOnboarding();

  const [file,    setFile]    = useState(null);
  const [loading, setLoading] = useState(false);
  const [drag,    setDrag]    = useState(false);
  const [error,   setError]   = useState('');
  const [preview, setPreview] = useState(null);

  const handleDrop = useCallback((e) => {
    e.preventDefault(); setDrag(false);
    const f = e.dataTransfer.files[0];
    if (f) { setFile(f); setPreview(null); }
  }, []);

  const handleFile = (e) => {
    const f = e.target.files[0];
    if (f) { setFile(f); setPreview(null); }
  };

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true); setError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      const data = await onboardUpload(fd);
      setProfile(data);
      setPreview(data);
    } catch (err) {
      setError(err?.detail || err?.message || 'Upload failed. Make sure the backend is running.');
    } finally { setLoading(false); }
  };

  return (
    <div className="container-md">
      <div style={{ textAlign:'center', marginBottom:40 }}>
        <h2 style={{ marginBottom:12 }}>Upload Your Dataset</h2>
        <p>Drop in your CSV, Parquet, or JSON file. Our AI will auto-profile your schema.</p>
      </div>

      {/* Drop Zone */}
      <div
        onDragOver={e => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={handleDrop}
        style={{
          border: `2px dashed ${drag ? 'var(--accent-1)' : file ? 'var(--success)' : 'var(--border)'}`,
          borderRadius: 'var(--radius-lg)',
          padding: '60px 24px',
          textAlign: 'center',
          cursor: 'pointer',
          background: drag ? 'rgba(59,130,246,.05)' : file ? 'rgba(16,185,129,.04)' : 'var(--bg-card)',
          transition: 'all .2s',
        }}
        onClick={() => document.getElementById('file-input').click()}
      >
        <input id="file-input" type="file" accept=".csv,.parquet,.json" style={{ display:'none' }} onChange={handleFile} />
        <div style={{ width:64,height:64,borderRadius:16,background:file?'rgba(16,185,129,.15)':'rgba(59,130,246,.12)',border:`1px solid ${file?'rgba(16,185,129,.3)':'rgba(59,130,246,.25)'}`,display:'flex',alignItems:'center',justifyContent:'center',margin:'0 auto 20px' }}>
          {file ? <FileText size={28} color="var(--success)"/> : <Upload size={28} color="var(--accent-1)"/>}
        </div>
        {file ? (
          <>
            <h4 style={{ marginBottom:8, color:'var(--success)' }}>{file.name}</h4>
            <p style={{ fontSize:14 }}>{(file.size/1024/1024).toFixed(2)} MB · Click to change</p>
          </>
        ) : (
          <>
            <h4 style={{ marginBottom:8 }}>Drag & drop your dataset here</h4>
            <p style={{ fontSize:14 }}>CSV, Parquet, or JSON · Max 100 MB</p>
            <div style={{ marginTop:16, display:'flex', gap:8, justifyContent:'center' }}>
              {['CSV','Parquet','JSON'].map(t => <span key={t} className="badge badge-blue">{t}</span>)}
            </div>
          </>
        )}
      </div>

      {error && <div className="alert alert-error mt-4"><AlertCircle size={16}/>{error}</div>}

      {/* Profile results */}
      {preview && (
        <div className="card mt-6 animate-fade-up">
          <h4 style={{ marginBottom:16, display:'flex', alignItems:'center', gap:8 }}>
            <Table size={18} color="var(--accent-1)"/> Dataset Profile
          </h4>
          <div className="grid-3" style={{ gap:16, marginBottom:20 }}>
            {[
              { label:'Rows',    val: preview.row_count    ?? preview.rows    ?? '—' },
              { label:'Columns', val: preview.column_count ?? preview.columns ?? '—' },
              { label:'Type',    val: preview.interaction_type ?? 'Auto-detected' },
            ].map(m => (
              <div key={m.label} style={{ textAlign:'center', padding:'16px', background:'var(--bg-surface)', borderRadius:'var(--radius)' }}>
                <div style={{ fontFamily:'Outfit',fontWeight:700,fontSize:'1.6rem', background:'linear-gradient(135deg,#3b82f6,#818cf8)',WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent' }}>{m.val}</div>
                <div style={{ color:'var(--text-secondary)',fontSize:13 }}>{m.label}</div>
              </div>
            ))}
          </div>
          {preview.candidate_id_columns?.length > 0 && (
            <div style={{ marginBottom:12 }}>
              <span style={{ fontSize:13, color:'var(--text-secondary)' }}>Detected ID columns: </span>
              {preview.candidate_id_columns.map(c => <span key={c} className="badge badge-cyan" style={{marginLeft:4}}>{c}</span>)}
            </div>
          )}
          <div className="alert alert-success" style={{ marginTop:12 }}>
            Profile complete! Review and continue to map columns.
          </div>
        </div>
      )}

      <div style={{ display:'flex', justifyContent:'flex-end', marginTop:32, gap:12 }}>
        {!preview ? (
          <button className="btn btn-primary" onClick={handleUpload} disabled={!file || loading}>
            {loading ? <><span className="animate-spin" style={{display:'inline-block',width:16,height:16,border:'2px solid rgba(255,255,255,.3)',borderTopColor:'#fff',borderRadius:'50%'}}/>Profiling…</> : <>Upload & Profile <ArrowRight size={16}/></>}
          </button>
        ) : (
          <button className="btn btn-primary" onClick={() => navigate('/onboarding/schema')}>
            Continue to Schema Mapping <ArrowRight size={16}/>
          </button>
        )}
      </div>
    </div>
  );
}
