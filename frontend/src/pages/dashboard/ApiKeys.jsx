import { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import { regenerateKeys } from '../../api/client';
import KeyDisplay from '../../components/KeyDisplay';
import { RefreshCw, ShieldAlert, Check, EyeOff } from 'lucide-react';

export default function ApiKeys() {
  const { user, setUser } = useAuth();
  const [loading,    setLoading]    = useState(false);
  const [confirm,    setConfirm]    = useState(false);
  const [success,    setSuccess]    = useState(false);
  const [newKeys,    setNewKeys]    = useState(null);
  const [storedSk,   setStoredSk]   = useState(() => localStorage.getItem('aipod_sk'));
  const [dismissed,  setDismissed]  = useState(false);
  const [error,      setError]      = useState('');

  // Remove aipod_sk from localStorage when user leaves this page
  useEffect(() => {
    return () => {
      localStorage.removeItem('aipod_sk');
    };
  }, []);

  const pk = newKeys?.public_key || user?.public_key || localStorage.getItem('aipod_pk') || '';
  const sk = !dismissed ? (storedSk || newKeys?.private_key || null) : null;

  const handleDismissSk = () => {
    localStorage.removeItem('aipod_sk');
    setStoredSk(null);
    setNewKeys(null);
    setDismissed(true);
  };

  const handleRotate = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await regenerateKeys();
      setNewKeys(data);
      localStorage.setItem('aipod_pk', data.public_key);
      // Remove from localStorage; only held in component state during this view
      localStorage.removeItem('aipod_sk');
      setStoredSk(data.private_key);
      setDismissed(false);
      if (setUser) {
        setUser(prev => (prev ? { ...prev, public_key: data.public_key } : prev));
      }
      setSuccess(true);
      setConfirm(false);
    } catch (err) {
      setError(err?.message || 'Failed to regenerate keys');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div style={{ marginBottom:32 }}>
        <h3 style={{ marginBottom:8 }}>API Keys</h3>
        <p style={{ fontSize:14 }}>Manage your public and private API keys. Rotate keys if you suspect a compromise.</p>
      </div>

      {success && (
        <div className="alert alert-success mb-6">
          <Check size={16}/> Keys rotated successfully. Copy this secret key now. After you leave this page it cannot be shown again.
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
            {pk ? (
              <KeyDisplay label="" value={pk} secret={false} />
            ) : (
              <div style={{ fontSize:13, color:'var(--text-muted)' }}>No public key available.</div>
            )}
          </div>

          <div className="divider" style={{ margin:'8px 0' }}/>

          {/* Private key */}
          <div>
            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:8 }}>
              <span className="badge badge-red">Private</span>
              <span style={{ fontSize:13, color:'var(--text-secondary)' }}>Backend use only — never expose in client code (sk-…)</span>
            </div>
            {sk ? (
              <div>
                <KeyDisplay label="" value={sk} secret={true} />
                <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginTop:10, flexWrap:'wrap', gap:8 }}>
                  <div style={{ fontSize:12, color:'var(--accent-1)' }}>
                    ⚠️ Copy this secret key now. After you leave this page it cannot be shown again.
                  </div>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={handleDismissSk}
                    style={{ fontSize:12, padding:'4px 10px' }}
                  >
                    I have copied my secret key
                  </button>
                </div>
              </div>
            ) : (
              <div style={{
                padding:'14px 16px', background:'var(--bg-surface)',
                borderRadius:'var(--radius-sm)', border:'1px dashed var(--border)',
              }}>
                <div style={{ display:'flex', alignItems:'center', gap:8, color:'var(--text-secondary)' }}>
                  <EyeOff size={15} style={{ opacity:0.7 }}/>
                  <span style={{ fontSize:13, fontWeight:500 }}>Private key is hidden for security.</span>
                </div>
                <p style={{ fontSize:12, color:'var(--text-muted)', margin:'6px 0 0 23px' }}>
                  Private keys are only shown once upon creation or rotation. Regenerate below to issue a new private key.
                </p>
              </div>
            )}
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
                ['GET /v1/dashboard/*',      '❌','✅'],
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
