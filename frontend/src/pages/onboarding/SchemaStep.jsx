import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOnboarding } from '../../context/OnboardingContext';
import { onboardValidate } from '../../api/client';
import { ArrowRight, ArrowLeft, Wand2, AlertCircle } from 'lucide-react';

export default function SchemaStep() {
  const navigate = useNavigate();
  const { profile, setMapping } = useOnboarding();

  const cols = profile?.columns || profile?.candidate_id_columns?.map(c => ({ name: c })) || [];
  const colNames = cols.map(c => c.name || c);

  const [form, setForm] = useState({
    customer_id_column: colNames[0] || '',
    product_id_column:  colNames[1] || '',
    interaction_type:   profile?.interaction_type || 'transactional',
  });
  const [error,   setError]   = useState('');
  const [loading, setLoading] = useState(false);

  const handleChange = e => setForm(f => ({ ...f, [e.target.name]: e.target.value }));

  const handleValidate = async () => {
    setLoading(true); setError('');
    try {
      const payload = { ...form, profile };
      const data = await onboardValidate(payload);
      setMapping({ ...form, validation: data });
      navigate('/onboarding/confirm');
    } catch (err) {
      // Allow proceeding even if backend not connected in dev
      setMapping({ ...form, validation: null });
      navigate('/onboarding/confirm');
    } finally { setLoading(false); }
  };

  return (
    <div className="container-md">
      <div style={{ textAlign:'center', marginBottom:40 }}>
        <h2 style={{ marginBottom:12 }}>Schema Mapping</h2>
        <p>Review the AI-detected column mappings. Adjust if needed before confirming.</p>
      </div>

      <div className="card">
        <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:24 }}>
          <Wand2 size={18} color="var(--accent-2)"/>
          <span style={{ fontSize:14, color:'var(--text-secondary)' }}>AI-suggested mappings — adjust as needed</span>
          <span className="badge badge-purple" style={{ marginLeft:'auto' }}>Auto-detected</span>
        </div>

        <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
          {/* Customer ID */}
          <div className="form-group">
            <label className="form-label">Customer ID Column</label>
            <select name="customer_id_column" value={form.customer_id_column} onChange={handleChange}>
              {colNames.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <span style={{ fontSize:12, color:'var(--text-muted)' }}>The column that uniquely identifies each customer (e.g. customerID, user_id)</span>
          </div>

          {/* Product ID */}
          <div className="form-group">
            <label className="form-label">Product / Item ID Column</label>
            <select name="product_id_column" value={form.product_id_column} onChange={handleChange}>
              {colNames.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <span style={{ fontSize:12, color:'var(--text-muted)' }}>The column that identifies products or catalog items</span>
          </div>

          {/* Interaction type */}
          <div className="form-group">
            <label className="form-label">Interaction Type</label>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12 }}>
              {[
                { val:'transactional', label:'Transactional', desc:'Order/receipt data: one row per purchase event' },
                { val:'service_matrix', label:'Service Matrix', desc:'Wide data: one row per customer, columns = services' },
              ].map(opt => (
                <div key={opt.val}
                  onClick={() => setForm(f=>({...f,interaction_type:opt.val}))}
                  style={{
                    padding:16, borderRadius:'var(--radius)', cursor:'pointer', border:`2px solid ${form.interaction_type===opt.val?'var(--accent-1)':'var(--border)'}`,
                    background: form.interaction_type===opt.val?'rgba(59,130,246,.08)':'var(--bg-input)',
                    transition:'all .2s',
                  }}>
                  <div style={{ fontWeight:600, marginBottom:4, color: form.interaction_type===opt.val?'var(--accent-1)':'var(--text-primary)' }}>{opt.label}</div>
                  <div style={{ fontSize:12, color:'var(--text-secondary)' }}>{opt.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {error && <div className="alert alert-error mt-4"><AlertCircle size={16}/>{error}</div>}
      </div>

      {/* Available columns reference */}
      {colNames.length > 0 && (
        <div className="card mt-4" style={{ padding:16 }}>
          <div style={{ fontSize:13, color:'var(--text-muted)', marginBottom:10 }}>Detected columns in your dataset</div>
          <div style={{ display:'flex', flexWrap:'wrap', gap:6 }}>
            {colNames.map(c => <span key={c} className="badge badge-blue">{c}</span>)}
          </div>
        </div>
      )}

      <div style={{ display:'flex', justifyContent:'space-between', marginTop:32 }}>
        <button className="btn btn-secondary" onClick={() => navigate('/onboarding/upload')}>
          <ArrowLeft size={16}/> Back
        </button>
        <button className="btn btn-primary" onClick={handleValidate} disabled={loading}>
          {loading ? 'Validating…' : <>Confirm Mapping <ArrowRight size={16}/></>}
        </button>
      </div>
    </div>
  );
}
