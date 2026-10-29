import { useState, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Zap, Menu, X } from 'lucide-react';

export default function Navbar() {
  const { user, logout }  = useAuth();
  const location          = useLocation();
  const navigate          = useNavigate();
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen]   = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener('scroll', onScroll);
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const handleLogout = () => { logout(); navigate('/'); };

  return (
    <nav style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 1000,
      padding: '0 24px',
      background: scrolled ? 'rgba(8,12,20,.92)' : 'transparent',
      backdropFilter: scrolled ? 'blur(20px)' : 'none',
      borderBottom: scrolled ? '1px solid rgba(99,179,237,.1)' : 'none',
      transition: 'all .3s ease',
    }}>
      <div style={{ maxWidth: 1200, margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: 68 }}>
        {/* Logo */}
        <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 36, height: 36, borderRadius: 10, background: 'linear-gradient(135deg,#3b82f6,#818cf8)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 14px rgba(59,130,246,.4)' }}>
            <Zap size={18} color="#fff" />
          </div>
          <span style={{ fontFamily: 'Outfit', fontWeight: 700, fontSize: 20 }}>
            AI<span style={{ background: 'linear-gradient(90deg,#3b82f6,#818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>_POD</span>
          </span>
        </Link>

        {/* Desktop nav */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }} className="desktop-nav">
          {!user ? (
            <>
              <Link to="/#features" className="btn btn-ghost">Features</Link>
              <Link to="/#how-it-works" className="btn btn-ghost">How it works</Link>
              <Link to="/signin" className="btn btn-secondary btn-sm">Sign In</Link>
              <Link to="/signup" className="btn btn-primary btn-sm">Get Started</Link>
            </>
          ) : (
            <>
              <Link to="/dashboard" className="btn btn-ghost">Dashboard</Link>
              <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>{user.company_name}</span>
              <button onClick={handleLogout} className="btn btn-secondary btn-sm">Sign Out</button>
            </>
          )}
        </div>

        {/* Mobile toggle */}
        <button onClick={() => setOpen(o => !o)} style={{ display: 'none', color: 'var(--text-primary)', padding: 8 }} className="mobile-menu-btn">
          {open ? <X size={22}/> : <Menu size={22}/>}
        </button>
      </div>

      {/* Mobile menu */}
      {open && (
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: 16, margin: '0 0 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {!user ? (
            <>
              <Link to="/" onClick={() => setOpen(false)} className="btn btn-ghost w-full">Home</Link>
              <Link to="/signin" onClick={() => setOpen(false)} className="btn btn-secondary w-full">Sign In</Link>
              <Link to="/signup" onClick={() => setOpen(false)} className="btn btn-primary w-full">Get Started</Link>
            </>
          ) : (
            <>
              <Link to="/dashboard" onClick={() => setOpen(false)} className="btn btn-ghost w-full">Dashboard</Link>
              <button onClick={() => { handleLogout(); setOpen(false); }} className="btn btn-secondary w-full">Sign Out</button>
            </>
          )}
        </div>
      )}

      <style>{`
        @media (max-width: 640px) {
          .desktop-nav { display: none !important; }
          .mobile-menu-btn { display: block !important; }
        }
      `}</style>
    </nav>
  );
}
