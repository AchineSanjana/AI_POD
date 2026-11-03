import { createContext, useContext, useState, useEffect } from 'react';
import { getMe } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser]       = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('aipod_token');
    if (token) {
      getMe()
        .then(setUser)
        .catch((err) => {
          if (err?.status === 401) {
            // Only clear the session JWT if unauthorized, preserving aipod_pk / aipod_sk
            localStorage.removeItem('aipod_token');
          }
          setUser(null);
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = (token, userData) => {
    localStorage.setItem('aipod_token', token);
    if (userData.public_key) localStorage.setItem('aipod_pk', userData.public_key);
    setUser(userData);
  };

  const logout = () => {
    localStorage.removeItem('aipod_token');
    localStorage.removeItem('aipod_pk');
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, setUser, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
