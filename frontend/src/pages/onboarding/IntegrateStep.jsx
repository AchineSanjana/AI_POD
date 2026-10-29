import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useOnboarding } from '../../context/OnboardingContext';
import { getRecommendations } from '../../api/client';
import CodeBlock from '../../components/CodeBlock';
import KeyDisplay from '../../components/KeyDisplay';
import { Key, Code2, Package, ShoppingBag, Zap, ArrowRight, Search } from 'lucide-react';

export default function IntegrateStep() {
  const { keys, tenantId } = useOnboarding();
  const pk = keys.pk || localStorage.getItem('aipod_pk') || 'pk-live-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx';
  const sk = keys.sk || localStorage.getItem('aipod_sk') || 'sk-live-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx';

  const [sdkTab,    setSdkTab]    = useState(0);
  const [testId,    setTestId]    = useState('');
  const [testResult,setTestResult]= useState(null);
  const [testing,   setTesting]   = useState(false);

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
      \`<div class="product">\${item.product_name}</div\>\`
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
    setTesting(true); setTestResult(null);
    try {
      const data = await getRecommendations(testId, 5);
      setTestResult(data);
    } catch {
      // Mock response for demo
      setTestResult({
        tenant_id: tenantId || 'demo',
        customer_id: testId,
        recommendations: [
          { rank:1, product_id:'P001', product_name:'Online Security',  category:'Add-on' },
          { rank:2, product_id:'P002', product_name:'Tech Support',      category:'Add-on' },
          { rank:3, product_id:'P003', product_name:'Streaming TV',      category:'Entertainment' },
        ],
        fallback: false,
      });
    } finally { setTesting(false); }
  };

  return (
    <div className="container-md">
      {/* Header */}
      <div style={{ textAlign:'center', marginBottom:48 }}>
        <div style={{ fontSize:48, marginBottom:16 }}>🎉</div>
        <h2 style={{ marginBottom:12 }}>You're live! Integrate AI_POD</h2>
        <p>Copy the snippet below and drop it into your website. Recommendations are ready.</p>
      </div>

      {/* Section A: API Keys */}
      <div className="card mb-6">
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:20 }}>
          <Key size={18} color="var(--accent-1)"/>
          <h4>Your API Keys</h4>
        </div>
        <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
          <KeyDisplay label="Public Key (for client-side embedding)" value={pk} secret={false} />
          <KeyDisplay label="Private Key (backend use only — never expose publicly)" value={sk} secret={true} />
        </div>
        <div className="alert alert-warning mt-4">
          <Zap size={14}/> Your private key will not be shown again after this page. Save it securely now.
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
        <p style={{ fontSize:14, marginBottom:16 }}>Enter a customer_id from your dataset to see live recommendations.</p>
        <div style={{ display:'flex', gap:12 }}>
          <input value={testId} onChange={e=>setTestId(e.target.value)} placeholder="e.g. 7590-VHVEG" />
          <button className="btn btn-primary btn-sm" onClick={handleTest} disabled={!testId || testing} style={{ whiteSpace:'nowrap' }}>
            {testing ? 'Loading…' : 'Get Recs'}
          </button>
        </div>

        {testResult && (
          <div style={{ marginTop:20 }}>
            <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
              {testResult.recommendations?.map(r => (
                <div key={r.rank} style={{ display:'flex', alignItems:'center', gap:12, padding:'10px 14px', background:'var(--bg-surface)', borderRadius:'var(--radius-sm)', border:'1px solid var(--border)' }}>
                  <div style={{ width:28,height:28,borderRadius:'50%',background:'linear-gradient(135deg,#3b82f6,#818cf8)',display:'flex',alignItems:'center',justifyContent:'center',fontSize:12,fontWeight:700,color:'#fff',flexShrink:0 }}>
                    {r.rank}
                  </div>
                  <div>
                    <div style={{ fontWeight:600, fontSize:14 }}>{r.product_name}</div>
                    {r.category && <div style={{ fontSize:12, color:'var(--text-muted)' }}>{r.category}</div>}
                  </div>
                  {testResult.fallback && r.rank === 1 && <span className="badge badge-yellow" style={{ marginLeft:'auto' }}>Fallback</span>}
                </div>
              ))}
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
