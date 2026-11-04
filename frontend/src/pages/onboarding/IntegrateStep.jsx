import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useOnboarding } from '../../context/OnboardingContext';
import { getRecommendations, getSampleCustomers } from '../../api/client';
import CodeBlock from '../../components/CodeBlock';
import KeyDisplay from '../../components/KeyDisplay';
import { Key, Code2, ShoppingBag, ArrowRight, Search, AlertCircle } from 'lucide-react';

const KEY_UNAVAILABLE = 'Key not available, regenerate in Dashboard > API Keys';

export default function IntegrateStep() {
  const { keys, tenantId } = useOnboarding();
  const pk = keys.pk || localStorage.getItem('aipod_pk') || KEY_UNAVAILABLE;

  const [sdkTab,          setSdkTab]          = useState(0);
  const [testId,          setTestId]          = useState('');
  const [sampleCustomers, setSampleCustomers] = useState([]);
  const [testResult,      setTestResult]      = useState(null);
  const [testError,       setTestError]       = useState('');
  const [testing,         setTesting]         = useState(false);

  useEffect(() => {
    let isMounted = true;
    const fetchSamples = async () => {
      try {
        const res = await getSampleCustomers(10, pk !== KEY_UNAVAILABLE ? pk : null);
        if (isMounted) {
          const ids = res?.customer_ids || (Array.isArray(res) ? res : []);
          setSampleCustomers(ids);
          if (ids.length > 0) {
            setTestId((current) => current || ids[0]);
          }
        }
      } catch (err) {
        console.warn('Could not load sample customers:', err);
      }
    };
    fetchSamples();
    return () => { isMounted = false; };
  }, [pk]);

  const htmlSnippet = `<script
  src="https://api.aipod.io/v1/sdk.js"
  data-tenant-key="${pk}">
</script>

<script>
  // Track events
  aipod.track('view', { product_id: 'SKU-001' });
  aipod.track('purchase', { product_id: 'SKU-001' });

  // Identify on login
  aipod.identify('cust_12345');

  // Render recommendations
  aipod.getRecommendations({
    top_n: 4,
    containerId: 'ai-recs',
    template: (item) =>
      \`<div class="product">\${item.product_name}</div>\`
  });
</script>`;

  const npmSnippet = `npm install @aipod/sdk

import { AIPod } from '@aipod/sdk';

const aipod = new AIPod({ tenantKey: '${pk}' });

aipod.track('view', { product_id: 'SKU-001' });
aipod.identify('cust_12345');

const recs = await aipod.getRecommendations({ top_n: 5 });`;

  const apiSnippet = `curl -X GET \\
  "https://api.aipod.io/v1/recommendations/cust_12345?top_n=5" \\
  -H "X-API-Key: ${pk}"

# Response
{
  "tenant_id": "${tenantId || 'your_tenant'}",
  "customer_id": "cust_12345",
  "recommendations": [
    { "rank": 1, "product_id": "P001", "product_name": "Online Security" },
    { "rank": 2, "product_id": "P002", "product_name": "Tech Support" }
  ],
  "fallback": false
}`;

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    setTestError('');
    try {
      const data = await getRecommendations(
        testId,
        5,
        pk !== KEY_UNAVAILABLE ? pk : null,
        { 'X-AIPOD-Source': 'wizard-test' }
      );
      setTestResult(data);
    } catch (err) {
      setTestError(err?.message || err?.detail || 'Failed to fetch recommendations.');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="container-md">
      {/* Header */}
      <div style={{ textAlign:'center', marginBottom:48 }}>
        <div style={{ fontSize:48, marginBottom:16 }}>🎉</div>
        <h2 style={{ marginBottom:12 }}>You're live! Integrate AI_POD</h2>
        <p>Copy the snippet below and drop it into your website. Recommendations are ready.</p>
      </div>

      {/* Section A: API Key */}
      <div className="card mb-6">
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:20 }}>
          <Key size={18} color="var(--accent-1)"/>
          <h4>Your API Key</h4>
        </div>
        <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
          <KeyDisplay label="Public Key (for client-side embedding)" value={pk} secret={false} />
        </div>
      </div>

      {/* Section B: SDK Installation */}
      <div className="card mb-6">
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:20 }}>
          <Code2 size={18} color="var(--accent-2)"/>
          <h4>SDK Installation</h4>
        </div>
        <div className="tabs mb-4">
          {['HTML Snippet','npm Package','REST API'].map((t,i) => (
            <button key={t} className={`tab-btn${sdkTab===i?' active':''}`} onClick={() => setSdkTab(i)}>{t}</button>
          ))}
        </div>
        {sdkTab === 0 && <CodeBlock code={htmlSnippet} language="html" />}
        {sdkTab === 1 && <CodeBlock code={npmSnippet}  language="javascript" />}
        {sdkTab === 2 && <CodeBlock code={apiSnippet}  language="bash" />}
      </div>

      {/* Section C: Live test */}
      <div className="card mb-6">
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:20 }}>
          <Search size={18} color="var(--accent-3)"/>
          <h4>Test Your Recommendations</h4>
        </div>
        <p style={{ fontSize:14, marginBottom:16 }}>
          Select a sample customer or type any customer ID to see live recommendations.
        </p>
        <div style={{ display:'flex', gap:12, flexWrap:'wrap' }}>
          {sampleCustomers.length > 0 && (
            <select
              style={{ minWidth: 200, flex: '0 0 auto' }}
              value={sampleCustomers.includes(testId) ? testId : ''}
              onChange={e => {
                if (e.target.value) setTestId(e.target.value);
              }}
            >
              <option value="">Sample customers...</option>
              {sampleCustomers.map(id => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
          )}
          <input
            style={{ flex: 1, minWidth: 180 }}
            value={testId}
            onChange={e=>setTestId(e.target.value)}
            placeholder="e.g. 7590-VHVEG or type custom ID"
          />
          <button className="btn btn-primary btn-sm" onClick={handleTest} disabled={!testId || testing} style={{ whiteSpace:'nowrap' }}>
            {testing ? 'Loading…' : 'Get Recs'}
          </button>
        </div>

        {testError && (
          <div className="alert alert-error mt-4">
            <AlertCircle size={16}/> {testError}
          </div>
        )}

        {testResult && (
          <div style={{ marginTop:20 }}>
            {testResult.fallback && (
              <div className="alert alert-warning mb-4" style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
                <span>
                  <strong>Fallback Recommendations:</strong> Popularity-based recommendations active.
                  {testResult.reason && (
                    <span style={{ marginLeft: 6 }}>
                      (Reason: <code>{testResult.reason}</code>)
                    </span>
                  )}
                </span>
                <span className="badge badge-yellow">Fallback</span>
              </div>
            )}
            <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
              {testResult.recommendations?.length === 0 ? (
                <div style={{ fontSize: 13, color: 'var(--text-muted)', fontStyle: 'italic', padding: 8 }}>
                  No recommendations available for this customer.
                </div>
              ) : (
                testResult.recommendations?.map(r => (
                  <div key={r.rank} style={{ display:'flex', alignItems:'center', gap:12, padding:'10px 14px', background:'var(--bg-surface)', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
                    <div style={{ width:28,height:28,borderRadius:'50%',background:'linear-gradient(135deg,#3b82f6,#818cf8)',display:'flex',alignItems:'center',justifyContent:'center',fontSize:12,fontWeight:700,color:'#fff',flexShrink:0 }}>
                      {r.rank}
                    </div>
                    <div>
                      <div style={{ fontWeight:600, fontSize:14 }}>{r.product_name || r.product_id}</div>
                      {r.category && <div style={{ fontSize:12, color:'var(--text-muted)' }}>{r.category}</div>}
                    </div>
                    {testResult.fallback && r.rank === 1 && (
                      <span className="badge badge-yellow" style={{ marginLeft:'auto' }}>
                        {testResult.reason || 'Fallback'}
                      </span>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      {/* Go to Dashboard */}
      <div style={{ textAlign:'center' }}>
        <Link to="/dashboard" className="btn btn-primary btn-lg">
          <ShoppingBag size={18}/> Go to My Dashboard <ArrowRight size={18}/>
        </Link>
      </div>
    </div>
  );
}

