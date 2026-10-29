import { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useNavigate } from 'react-router-dom';
import { User, Lock, Trash2, Save, ShieldAlert, Eye, EyeOff } from 'lucide-react';

export default function Settings() {
  const { user, setUser, logout } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    company_name: user?.company_name || '',
    email:        user?.email        || '',
  });
  const [pwForm, setPwForm] = useState({ current:'', newPw:'', confirm:'' });
  const [showPw,  setShowPw]  = useState(false);
  const [saved,   setSaved]   = useState(false);
  const [danger,  setDanger]  = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState('');

  const handleSave = (e) => {
    e.preventDefault();
    setUser(u => ({ ...u, ...form }));
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  const handleDelete = () => {
    if (deleteConfirm === 'DELETE') {
      logout(); navigate('/');
    }
  };

  return (
    <div>
      <div style={{ marginBottom:32 }}>
        <h3 style={{ marginBottom:8 }}>Settings</h3>
        <p style={{ fontSize:14 }}>Manage your account profile and security.</p>
      </div>

      {/* Profile */}
      <div className="card mb-6">
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:24 }}>
          <User size={18} color="var(--accent-1)"/>
          <h4>Company Profile</h4>
        </div>
        <form onSubmit={handleSave} style={{ display:'flex', flexDirection:'column', gap:16, maxWidth:480 }}>
          <div className="form-group">
            <label className="form-label">Company Name</label>
            <input value={form.company_name} onChange={e=>setForm(f=>({...f,company_name:e.target.value}))} />
          </div>
          <div className="form-group">
            <label className="form-label">Email</label>
            <input type="email" value={form.email} onChange={e=>setForm(f=>({...f,email:e.target.value}))} />
          </div>
          <div className="form-group">
            <label className="form-label">Tenant ID</label>
            <input value={user?.tenant_id || ''} disabled style={{ opacity:.6 }} />
            <span style={{ fontSize:12, color:'var(--text-muted)' }}>Tenant ID cannot be changed after creation.</span>
          </div>
          <button type="submit" className="btn btn-primary btn-sm" style={{ alignSelf:'flex-start' }}>
            {saved ? '✓ Saved!' : <><Save size={14}/> Save Changes</>}
          </button>
        </form>
      </div>

      {/* Password */}
      <div className="card mb-6">
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:24 }}>
          <Lock size={18} color="var(--accent-2)"/>
          <h4>Change Password</h4>
        </div>
        <div style={{ display:'flex', flexDirection:'column', gap:16, maxWidth:480 }}>
          <div className="form-group">
            <label className="form-label">Current Password</label>
            <input type={showPw?'text':'password'} value={pwForm.current} onChange={e=>setPwForm(f=>({...f,current:e.target.value}))} placeholder="••••••••"/>
          </div>
          <div className="form-group">
            <label className="form-label">New Password</label>
            <input type={showPw?'text':'password'} value={pwForm.newPw}  onChange={e=>setPwForm(f=>({...f,newPw:e.target.value}))}   placeholder="Min 8 characters"/>
          </div>
          <div className="form-group">
            <label className="form-label">Confirm New Password</label>
            <input type={showPw?'text':'password'} value={pwForm.confirm} onChange={e=>setPwForm(f=>({...f,confirm:e.target.value}))} placeholder="Repeat new password"/>
          </div>
          <div style={{ display:'flex', gap:12, alignItems:'center' }}>
            <button className="btn btn-secondary btn-sm" onClick={()=>setShowPw(s=>!s)}>
              {showPw?<><EyeOff size={13}/>Hide</>:<><Eye size={13}/>Show</>}
            </button>
            <button className="btn btn-primary btn-sm" disabled={!pwForm.current||!pwForm.newPw}>
              <Lock size={13}/> Update Password
            </button>
          </div>
        </div>
      </div>

      {/* Danger zone */}
      <div className="card" style={{ border:'1px solid rgba(239,68,68,.25)', background:'rgba(239,68,68,.03)' }}>
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:16 }}>
          <ShieldAlert size={18} color="var(--danger)"/>
          <h4 style={{ color:'var(--danger)' }}>Danger Zone</h4>
        </div>
        <p style={{ fontSize:14, marginBottom:20 }}>Permanently delete your account, tenant configuration, and all associated data. This action is irreversible.</p>
        {!danger ? (
          <button className="btn btn-danger" onClick={()=>setDanger(true)}>
            <Trash2 size={14}/> Delete Account
          </button>
        ) : (
          <div style={{ display:'flex', flexDirection:'column', gap:12, maxWidth:400 }}>
            <p style={{ fontSize:14, color:'var(--danger)' }}>Type <strong>DELETE</strong> to confirm:</p>
            <input value={deleteConfirm} onChange={e=>setDeleteConfirm(e.target.value)} placeholder="DELETE" style={{ borderColor:'rgba(239,68,68,.4)' }}/>
            <div style={{ display:'flex', gap:8 }}>
              <button className="btn btn-danger btn-sm" onClick={handleDelete} disabled={deleteConfirm!=='DELETE'}>
                Confirm Delete
              </button>
              <button className="btn btn-ghost btn-sm" onClick={()=>{setDanger(false);setDeleteConfirm('');}}>Cancel</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
