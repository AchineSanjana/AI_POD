import { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { regenerateKeys } from '../../api/client';
import KeyDisplay from '../../components/KeyDisplay';
import { Key, RefreshCw, ShieldAlert, Check } from 'lucide-react';

export default function ApiKeys() {
  const { user, setUser } = useAuth();
  const [loading,   setLoading]   = useState(false);
  const [confirm,   setConfirm]   = useState(false);
  const [success,   setSuccess]   = useState(false);
  const [newKeys,   setNewKeys]   = useState(null);
  const [error,     setError]     = useState('');

  const pk = newKeys?.public_key  || localStorage.getItem('aipod_pk') || 'pk-live-xxxx…';
  const sk = newKeys?.private_key || localStorage.getItem('aipod_sk') || 'sk-live-xxxx…';

  const handleRotate = async () => {
    setLoading(true); setError('');
    try {
      const data = await regenerateKeys();
      setNewKeys(data);
      localStorage.setItem('aipod_pk', data.public_key);
      localStorage.setItem('aipod_sk', data.private_key);
      setSuccess(true); setConfirm(false);
    } catch (err) {
      setError(err.message || 'Failed to regenerate keys');
    } finally { setLoading(false); }
  };

  return (
    <div>
      <div style={{ marginBottom:32 }}>
        <h3 style={{ marginBottom:8 }}>API Keys</h3>
        <p style={{ fontSize:14 }}>Manage your public and private API keys. Rotate keys if you suspect a compromise.</p>
      </div>

      {success && (
        <div className="alert alert-success mb-6">
          <Check size={16}/> Keys rotated successfully. Save your new private key — it won't be shown again.
        </div>
      )}
      {error && <div className="alert alert-error mb-6">{error}</div>}

      {/* Keys */}
      <div className="card mb-6">
        <h4 style={{ marginBottom:20 }}>Active Keys</h4>
        <div style={{ display:'flex', flexDirection:'column', gap:16 }}>
          {/* Public key */}
          <div>
            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:8 }}>
              <span className="badge badge-blue">Public</span>
              <span style={{ fontSize:13, color:'var(--text-secondary)' }}>Safe for client-side embedding (pk-…)</span>
            </div>
            <KeyDisplay label="" value={pk} secret={false} />
          </div>

          <div className="divider" style={{ margin:'8px 0' }}/>

          {/* Private key */}
          <div>
            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:8 }}>
              <span className="badge badge-red">Private</span>
              <span style={{ fontSize:13, color:'var(--text-secondary)' }}>Backend use only — never expose in client code (sk-…)</span>
            </div>
            <KeyDisplay label="" value={sk} secret={true} />
          </div>
        </div>
      </div>

      {/* Permissions table */}
      <div className="card mb-6">
        <h4 style={{ marginBottom:16 }}>Key Permissions</h4>
        <div style={{ overflowX:'auto' }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:13 }}>
            <thead>
              <tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Endpoint','Public Key','Private Key'].map(h => (
                  <th key={h} style={{ textAlign:'left', padding:'8px 12px', color:'var(--text-muted)', fontWeight:600 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                ['GET /v1/recommendations', '✅','✅'],
                ['POST /v1/track',           '✅','✅'],
                ['POST /v1/onboard/*',       '❌','✅'],
                ['GET /v1/onboard/status',   '❌','✅'],
                ['POST /v1/retrain/*',       '❌','✅'],
                ['GET /v1/accounts/me',      '❌','✅'],
              ].map(([ep,...cols],i) => (
                <tr key={ep} style={{ borderBottom:'1px solid var(--border)', background: i%2?'var(--bg-surface)':'transparent' }}>
                  <td style={{ padding:'8px 12px' }}><code style={{ fontSize:12 }}>{ep}</code></td>
                  {cols.map((c,j) => <td key={j} style={{ padding:'8px 12px', textAlign:'center' }}>{c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Danger zone */}
      <div className="card" style={{ border:'1px solid rgba(239,68,68,.25)', background:'rgba(239,68,68,.03)' }}>
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:16 }}>
          <ShieldAlert size={18} color="var(--danger)"/>
          <h4 style={{ color:'var(--danger)' }}>Rotate Keys</h4>
        </div>
        <p style={{ fontSize:14, marginBottom:20 }}>Rotating will immediately invalidate your current keys. Any service using the old keys will stop working until updated.</p>

        {!confirm ? (
          <button className="btn btn-danger" onClick={() => setConfirm(true)}>
            <RefreshCw size={15}/> Rotate API Keys
          </button>
        ) : (
          <div style={{ display:'flex', gap:12, alignItems:'center' }}>
            <span style={{ fontSize:14, color:'var(--text-secondary)' }}>Are you sure? This cannot be undone.</span>
            <button className="btn btn-danger btn-sm" onClick={handleRotate} disabled={loading}>
              {loading ? 'Rotating…' : 'Yes, Rotate'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setConfirm(false)}>Cancel</button>
          </div>
        )}
      </div>
    </div>
  );
}
