import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOnboarding } from '../../context/OnboardingContext';
import { useAuth } from '../../context/AuthContext';
import { onboardConfirm } from '../../api/client';
import CodeBlock from '../../components/CodeBlock';
import { ArrowLeft, ArrowRight, CheckCircle2 } from 'lucide-react';

function buildYaml(tenantId, mapping) {
  return `tenants:
  ${tenantId}:
    customers:
      id_column: ${mapping?.customer_id_column || 'customer_id'}
    products:
      derived_from: ${mapping?.interaction_type === 'service_matrix' ? 'interaction_source' : 'transactional'}
      id_column: ${mapping?.product_id_column || 'product_id'}
    interactions:
      source: ${mapping?.interaction_type || 'transactional'}`;
}

export default function ConfirmStep() {
  const navigate = useNavigate();
  const { user }  = useAuth();
  const { mapping, setTenantId, setConfig } = useOnboarding();

  const defaultTenant = user?.tenant_id || 'my_tenant';
  const [tid,     setTid]     = useState(defaultTenant);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState('');

  const yaml = buildYaml(tid, mapping);

  const handleConfirm = async () => {
    setLoading(true); setError('');
    try {
      await onboardConfirm({ tenant_id: tid, mapping });
      setTenantId(tid);
      setConfig({ tenant_id: tid, mapping });
      navigate('/onboarding/training');
    } catch (err) {
      // In dev, proceed anyway
      setTenantId(tid);
      setConfig({ tenant_id: tid, mapping });
      navigate('/onboarding/training');
    } finally { setLoading(false); }
  };

  return (
    <div className="container-md">
      <div style={{ textAlign:'center', marginBottom:40 }}>
        <h2 style={{ marginBottom:12 }}>Confirm Your Configuration</h2>
        <p>Review the auto-generated config. This will be saved and used to train your models.</p>
      </div>

      {/* Summary card */}
      <div className="card mb-6">
        <h4 style={{ marginBottom:20 }}>Configuration Summary</h4>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
          {[
            { label:'Customer ID', val: mapping?.customer_id_column || '—' },
            { label:'Product ID',  val: mapping?.product_id_column  || '—' },
            { label:'Data Type',   val: mapping?.interaction_type   || 'transactional' },
            { label:'Models',      val: '4 (Content, CF, Hybrid, XGBoost)' },
          ].map(r => (
            <div key={r.label} style={{ padding:'12px 16px', background:'var(--bg-surface)', borderRadius:'var(--radius-sm)' }}>
              <div style={{ fontSize:11, color:'var(--text-muted)', marginBottom:4 }}>{r.label}</div>
              <div style={{ fontWeight:600, fontSize:14 }}>{r.val}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Tenant ID */}
      <div className="card mb-6">
        <h4 style={{ marginBottom:12 }}>Tenant ID</h4>
        <p style={{ fontSize:14, marginBottom:12 }}>This is your unique identifier across the platform. You can customise it below.</p>
        <input value={tid} onChange={e => setTid(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g,''))} placeholder="my_company" />
      </div>

      {/* YAML preview */}
      <div className="card mb-6">
        <h4 style={{ marginBottom:16 }}>Generated Configuration</h4>
        <CodeBlock code={yaml} language="yaml" />
      </div>

      {error && <div className="alert alert-error mb-4">{error}</div>}

      <div style={{ display:'flex', justifyContent:'space-between', marginTop:24 }}>
        <button className="btn btn-secondary" onClick={() => navigate('/onboarding/schema')}>
          <ArrowLeft size={16}/> Edit Mapping
        </button>
        <button className="btn btn-primary" onClick={handleConfirm} disabled={loading || !tid}>
          {loading ? 'Saving…' : <><CheckCircle2 size={16}/> Save & Start Training <ArrowRight size={16}/></>}
        </button>
      </div>
    </div>
  );
}
