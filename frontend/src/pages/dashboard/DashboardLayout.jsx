import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import {
  LayoutDashboard, Key, Brain, BarChart3,
  Settings, ExternalLink, LogOut, Zap, Menu, X, Sparkles,
} from 'lucide-react';
import { useState } from 'react';

const NAV = [
  { to:'/dashboard',          icon:LayoutDashboard, label:'Overview'        },
  { to:'/ui',                 icon:Sparkles,        label:'Recommendations', external: true },
  { to:'/dashboard/keys',     icon:Key,             label:'API Keys'        },
  { to:'/dashboard/model',    icon:Brain,           label:'Model Status'    },
  { to:'/dashboard/analytics',icon:BarChart3,       label:'Analytics'       },
  { to:'/dashboard/settings', icon:Settings,        label:'Settings'        },
];

export default function DashboardLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [sideOpen, setSideOpen] = useState(false);

  const handleLogout = () => { logout(); navigate('/'); };

  const Sidebar = () => (
    <aside style={{
      width:240, background:'var(--bg-surface)',
      borderRight:'1px solid var(--border)',
      display:'flex', flexDirection:'column',
      height:'100%', padding:'24px 0',
      flexShrink:0,
    }}>
      {/* Logo */}
      <div style={{ padding:'0 20px 24px', borderBottom:'1px solid var(--border)' }}>
        <NavLink to="/" style={{ display:'flex', alignItems:'center', gap:10 }}>
          <div style={{ width:34,height:34,borderRadius:9,background:'linear-gradient(135deg,#3b82f6,#818cf8)',display:'flex',alignItems:'center',justifyContent:'center' }}>
            <Zap size={16} color="#fff"/>
          </div>
          <span style={{ fontFamily:'Outfit',fontWeight:700,fontSize:18 }}>AI<span className="gradient-text">_POD</span></span>
        </NavLink>
        {user && (
          <div style={{ marginTop:16 }}>
            <div style={{ fontSize:13, fontWeight:600, color:'var(--text-primary)' }}>{user.company_name}</div>
            <div style={{ fontSize:11, color:'var(--text-muted)', fontFamily:'monospace', marginTop:2 }}>{user.tenant_id}</div>
          </div>
        )}
      </div>

      {/* Nav items */}
      <nav style={{ flex:1, padding:'16px 12px', display:'flex', flexDirection:'column', gap:2 }}>
        {NAV.map(item => item.external ? (
          <a key={item.to} href={item.to}
            style={{
              display:'flex', alignItems:'center', gap:10,
              padding:'10px 12px', borderRadius:'var(--radius-sm)',
              fontSize:14, fontWeight: 400,
              color: 'var(--text-secondary)',
              background: 'transparent',
              transition:'all .2s',
              textDecoration:'none',
            }}>
            <item.icon size={16}/>
            {item.label}
          </a>
        ) : (
          <NavLink key={item.to} to={item.to} end={item.to==='/dashboard'}
            style={({ isActive }) => ({
              display:'flex', alignItems:'center', gap:10,
              padding:'10px 12px', borderRadius:'var(--radius-sm)',
              fontSize:14, fontWeight: isActive ? 600 : 400,
              color: isActive ? '#fff' : 'var(--text-secondary)',
              background: isActive ? 'var(--accent-grad)' : 'transparent',
              boxShadow: isActive ? '0 2px 10px rgba(59,130,246,.3)' : 'none',
              transition:'all .2s',
              textDecoration:'none',
            })}>
            <item.icon size={16}/>
            {item.label}
          </NavLink>
        ))}
      </nav>

      {/* Bottom */}
      <div style={{ padding:'16px 12px', borderTop:'1px solid var(--border)', display:'flex', flexDirection:'column', gap:4 }}>
        <a href="/docs" target="_blank" rel="noreferrer"
          style={{ display:'flex',alignItems:'center',gap:10,padding:'9px 12px',fontSize:13,color:'var(--text-muted)',borderRadius:'var(--radius-sm)',transition:'color .2s' }}>
          <ExternalLink size={15}/> API Docs
        </a>
        <button onClick={handleLogout}
          style={{ display:'flex',alignItems:'center',gap:10,padding:'9px 12px',fontSize:13,color:'var(--text-muted)',borderRadius:'var(--radius-sm)',transition:'color .2s', width:'100%' }}>
          <LogOut size={15}/> Sign Out
        </button>
      </div>
    </aside>
  );

  return (
    <div style={{ display:'flex', height:'100vh', overflow:'hidden' }}>
      {/* Desktop sidebar */}
      <div style={{ display:'block' }} className="desktop-sidebar">
        <Sidebar />
      </div>

      {/* Mobile sidebar overlay */}
      {sideOpen && (
        <div style={{ position:'fixed',inset:0,zIndex:200, display:'flex' }}>
          <div style={{ position:'absolute',inset:0,background:'rgba(0,0,0,.6)' }} onClick={() => setSideOpen(false)}/>
          <div style={{ position:'relative',zIndex:1,height:'100%' }}>
            <Sidebar />
          </div>
        </div>
      )}

      {/* Main */}
      <div style={{ flex:1, overflow:'auto', display:'flex', flexDirection:'column' }}>
        {/* Mobile top bar */}
        <div style={{ display:'none', alignItems:'center', gap:12, padding:'12px 16px', borderBottom:'1px solid var(--border)', background:'var(--bg-surface)' }} className="mobile-topbar">
          <button onClick={() => setSideOpen(true)} style={{ color:'var(--text-primary)' }}><Menu size={22}/></button>
          <span style={{ fontFamily:'Outfit',fontWeight:700 }}>AI_POD</span>
        </div>
        <div style={{ flex:1, padding:'32px', overflowY:'auto' }}>
          <Outlet />
        </div>
      </div>

      <style>{`
        @media (max-width: 768px) {
          .desktop-sidebar { display: none !important; }
          .mobile-topbar   { display: flex !important; }
        }
      `}</style>
    </div>
  );
}
