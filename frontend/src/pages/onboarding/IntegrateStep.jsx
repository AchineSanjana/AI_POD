import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useOnboarding } from '../../context/OnboardingContext';
import { getRecommendations, getSampleCustomers, getCatalogProducts } from '../../api/client';
import CodeBlock from '../../components/CodeBlock';
import KeyDisplay from '../../components/KeyDisplay';
import SimilarResults from '../../components/SimilarResults';
import { Key, Code2, ShoppingBag, ArrowRight, Search, AlertCircle, Layers, Sparkles } from 'lucide-react';

const KEY_UNAVAILABLE = 'Key not available, regenerate in Dashboard > API Keys';

export default function IntegrateStep() {
  const { keys, tenantId } = useOnboarding();
  const rawPk = keys.pk || localStorage.getItem('aipod_pk');
  const isPkAvailable = Boolean(rawPk && rawPk !== KEY_UNAVAILABLE && !rawPk.startsWith('sk-'));

  const [sdkTab,          setSdkTab]          = useState(0);
  const [testId,          setTestId]          = useState('');
  const [sampleCustomers, setSampleCustomers] = useState([]);
  const [testResult,      setTestResult]      = useState(null);
  const [testError,       setTestError]       = useState('');
  const [testing,         setTesting]         = useState(false);

  // Similar Products Panel State
  const [catalogProducts, setCatalogProducts] = useState([]);
  const [catalogTotal,    setCatalogTotal]    = useState(null);
  const [catalogLoading,  setCatalogLoading]  = useState(true);
  const [productSearch,   setProductSearch]   = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [selectedProduct, setSelectedProduct] = useState('');
  const [simTopN,         setSimTopN]         = useState(4);
  const [simSameCategory, setSimSameCategory] = useState(true);

  // API Base for snippets
  const apiBase = typeof window !== 'undefined'
    ? (window.location.port === '5173' ? 'http://127.0.0.1:8000' : window.location.origin)
    : 'http://127.0.0.1:8000';

  // Fetch sample customers for recommendation test
  useEffect(() => {
    let isMounted = true;
    const fetchSamples = async () => {
      try {
        const res = await getSampleCustomers(10, isPkAvailable ? rawPk : null);
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
  }, [isPkAvailable, rawPk]);

  // Debounce product search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(productSearch);
    }, 300);
    return () => clearTimeout(timer);
  }, [productSearch]);

  // Fetch catalog products
  useEffect(() => {
    let isMounted = true;
    setCatalogLoading(true);
    getCatalogProducts({
      query: debouncedSearch,
      status: 'active',
      page: 1,
      pageSize: 25,
    })
      .then((res) => {
        if (isMounted) {
          const items = res.items || [];
          setCatalogProducts(items);
          setCatalogTotal(res.total ?? 0);
          if (items.length > 0) {
            setSelectedProduct((prev) => prev || items[0].product_id);
          }
          setCatalogLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          console.warn('Could not load catalogue products for testing:', err);
          setCatalogLoading(false);
        }
      });

    return () => { isMounted = false; };
  }, [debouncedSearch]);

  const htmlSnippet = `<script
  src="${apiBase}/sdk.js"
  data-tenant-key="${isPkAvailable ? rawPk : KEY_UNAVAILABLE}">
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

const aipod = new AIPod({ tenantKey: '${isPkAvailable ? rawPk : KEY_UNAVAILABLE}' });

aipod.track('view', { product_id: 'SKU-001' });
aipod.identify('cust_12345');

const recs = await aipod.getRecommendations({ top_n: 5 });`;

  const apiSnippet = `curl -X GET \\
  "${apiBase}/v1/recommendations/cust_12345?top_n=5" \\
  -H "X-API-Key: ${isPkAvailable ? rawPk : KEY_UNAVAILABLE}"

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

  const similarScriptSnippet = `<script
  src="${apiBase}/sdk.js"
  data-tenant-key="${isPkAvailable ? rawPk : KEY_UNAVAILABLE}"
  data-currency="LKR"
  data-locale="en-LK">
</script>`;

  const similarWidgetSnippet = `// Render similar products widget
aipod.getSimilar({
  product_id: '${selectedProduct || 'PRODUCT_ID'}',
  containerId: 'similar-products',
  top_n: ${simTopN},
  same_category: ${simSameCategory}
});`;

  const compareWidgetSnippet = `// Render product comparison matrix
aipod.compare({
  product_id: '${selectedProduct || 'PRODUCT_ID'}',
  containerId: 'compare-products'
});`;

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    setTestError('');
    try {
      const data = await getRecommendations(
        testId,
        5,
        isPkAvailable ? rawPk : null,
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
        <p>Copy the snippet below and drop it into your website. Recommendations and Similar Products are ready.</p>
      </div>

      {/* Section A: API Key */}
      <div className="card mb-6">
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:20 }}>
          <Key size={18} color="var(--accent-1)"/>
          <h4>Your API Key</h4>
        </div>
        <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
          {isPkAvailable ? (
            <KeyDisplay label="Public Key (for client-side embedding)" value={rawPk} secret={false} />
          ) : (
            <div className="alert alert-warning" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span>{KEY_UNAVAILABLE}</span>
              <Link to="/dashboard/keys" className="btn btn-secondary btn-sm">Go to API Keys</Link>
            </div>
          )}
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

      {/* Section C: Live test recommendations */}
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

      {/* Section D: Test Similar Products (Step S3) */}
      <div className="card mb-6" id="similar-products-test-panel">
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:16 }}>
          <div style={{ display:'flex', alignItems:'center', gap:10 }}>
            <Layers size={18} color="var(--accent-1)"/>
            <h4 style={{ margin:0 }}>Test Similar Products</h4>
          </div>
          <span className="badge badge-blue">Storefront Feature</span>
        </div>

        <p style={{ fontSize:14, color:'var(--text-secondary)', marginBottom:20 }}>
          Search for an active product in your catalogue to preview similar items computed dynamically using category, specs, and price similarity.
        </p>

        {/* Check if catalogue is empty */}
        {catalogTotal === 0 && !catalogLoading && !debouncedSearch ? (
          <div style={{ textAlign: 'center', padding: '32px 16px', background: 'var(--bg-surface)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
            <AlertCircle size={28} color="var(--accent-warn)" style={{ marginBottom: 10, opacity: 0.8 }} />
            <div style={{ fontSize: 15, fontWeight: 600 }}>Catalogue is currently empty.</div>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4, marginBottom: 16 }}>
              Add products in the <Link to="/dashboard/catalog" style={{ color: 'var(--accent-1)', textDecoration: 'underline' }}>Catalogue page</Link> first to test similar product recommendations.
            </p>
            <Link to="/dashboard/catalog" className="btn btn-secondary btn-sm">
              Go to Catalogue
            </Link>
          </div>
        ) : (
          <div>
            {/* Search and Picker Bar */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
              <div style={{ position: 'relative' }}>
                <Search size={14} color="var(--text-muted)" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)' }} />
                <input
                  type="text"
                  placeholder="Filter active products…"
                  value={productSearch}
                  onChange={(e) => setProductSearch(e.target.value)}
                  style={{ paddingLeft: 34, width: '100%' }}
                />
              </div>

              <div>
                <select
                  value={selectedProduct}
                  onChange={(e) => setSelectedProduct(e.target.value)}
                  disabled={catalogLoading || catalogProducts.length === 0}
                  style={{ width: '100%' }}
                >
                  {catalogProducts.length === 0 ? (
                    <option value="">No matching active products</option>
                  ) : (
                    catalogProducts.map((p) => (
                      <option key={p.product_id} value={p.product_id}>
                        {p.product_name} ({p.product_id})
                      </option>
                    ))
                  )}
                </select>
              </div>
            </div>

            {/* Results Component */}
            <div style={{ marginBottom: 28 }}>
              <SimilarResults
                productId={selectedProduct}
                pk={isPkAvailable ? rawPk : null}
                initialTopN={simTopN}
                initialSameCategory={simSameCategory}
                showControls={true}
                onTopNChange={setSimTopN}
                onSameCategoryChange={setSimSameCategory}
              />
            </div>

            {/* Copy-Ready Snippets */}
            <div style={{ borderTop: '1px solid var(--border)', paddingTop: 24, marginTop: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
                <Sparkles size={16} color="var(--accent-2)" />
                <h5 style={{ margin: 0 }}>Embed Similar Products on Your Product Pages</h5>
              </div>

              {/* Note on CORS */}
              <div
                style={{
                  background: 'rgba(59, 130, 246, 0.08)',
                  border: '1px solid rgba(59, 130, 246, 0.25)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '12px 14px',
                  fontSize: 13,
                  color: 'var(--text-secondary)',
                  marginBottom: 16,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                }}
              >
                <AlertCircle size={16} color="var(--accent-1)" style={{ flexShrink: 0 }} />
                <span>
                  Your storefront's origin must be allowed by the API (<code>CORS_ORIGINS</code>) before the widgets load on your site.
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
                    1. Include the SDK in your HTML head or before closing &lt;/body&gt;:
                  </div>
                  <CodeBlock code={similarScriptSnippet} language="html" />
                </div>

                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
                    2. Render Similar Products Carousel:
                  </div>
                  <CodeBlock code={similarWidgetSnippet} language="javascript" />
                </div>

                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
                    3. Render Side-by-Side Comparison Matrix:
                  </div>
                  <CodeBlock code={compareWidgetSnippet} language="javascript" />
                </div>
              </div>
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
