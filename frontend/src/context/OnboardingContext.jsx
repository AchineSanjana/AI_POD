import { createContext, useContext, useState } from 'react';

const OnboardingContext = createContext(null);

export function OnboardingProvider({ children }) {
  const [profile, setProfile]     = useState(null);   // profiler output
  const [mapping, setMapping]     = useState(null);   // schema mapping
  const [config,  setConfig]      = useState(null);   // confirmed config
  const [tenantId, setTenantId]   = useState('');
  const [keys, setKeys]           = useState({ pk: '', sk: '' });

  const reset = () => {
    setProfile(null); setMapping(null);
    setConfig(null);  setTenantId(''); setKeys({ pk:'', sk:'' });
  };

  return (
    <OnboardingContext.Provider value={{
      profile, setProfile,
      mapping, setMapping,
      config,  setConfig,
      tenantId, setTenantId,
      keys, setKeys,
      reset,
    }}>
      {children}
    </OnboardingContext.Provider>
  );
}

export const useOnboarding = () => useContext(OnboardingContext);
