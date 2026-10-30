import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { OnboardingProvider } from './context/OnboardingContext';

// Pages
import Landing      from './pages/Landing';
import Features     from './pages/Features';
import HowItWorks   from './pages/HowItWorks';
import SignUp       from './pages/SignUp';
import SignIn     from './pages/SignIn';

import OnboardingLayout from './pages/onboarding/OnboardingLayout';
import UploadStep       from './pages/onboarding/UploadStep';
import SchemaStep       from './pages/onboarding/SchemaStep';
import ConfirmStep      from './pages/onboarding/ConfirmStep';
import TrainingStep     from './pages/onboarding/TrainingStep';
import IntegrateStep    from './pages/onboarding/IntegrateStep';

import DashboardLayout from './pages/dashboard/DashboardLayout';
import Overview        from './pages/dashboard/Overview';
import ApiKeys         from './pages/dashboard/ApiKeys';
import ModelStatus     from './pages/dashboard/ModelStatus';
import Analytics       from './pages/dashboard/Analytics';
import Settings        from './pages/dashboard/Settings';

function PrivateRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return (
    <div style={{ minHeight:'100vh', display:'flex', alignItems:'center', justifyContent:'center' }}>
      <div style={{ width:40,height:40,borderRadius:'50%',border:'3px solid rgba(59,130,246,.2)',borderTopColor:'#3b82f6',animation:'spin 1s linear infinite' }}/>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
  return user ? children : <Navigate to="/signin" replace />;
}

function UiRedirect() {
  useEffect(() => {
    window.location.href = '/ui';
  }, []);
  return null;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/"            element={<Landing    />} />
      <Route path="/features"    element={<Features   />} />
      <Route path="/how-it-works" element={<HowItWorks />} />
      <Route path="/signup"      element={<SignUp     />} />
      <Route path="/signin"      element={<SignIn     />} />
      <Route path="/ui"          element={<UiRedirect />} />
      <Route path="/demo"        element={<UiRedirect />} />

      {/* Onboarding wizard */}
      <Route path="/onboarding" element={<OnboardingLayout />}>
        <Route index            element={<Navigate to="/onboarding/upload" replace />} />
        <Route path="upload"    element={<UploadStep   />} />
        <Route path="schema"    element={<SchemaStep   />} />
        <Route path="confirm"   element={<ConfirmStep  />} />
        <Route path="training"  element={<TrainingStep />} />
        <Route path="integrate" element={<IntegrateStep/>} />
      </Route>

      {/* Dashboard — protected */}
      <Route path="/dashboard" element={<PrivateRoute><DashboardLayout /></PrivateRoute>}>
        <Route index              element={<Overview    />} />
        <Route path="keys"        element={<ApiKeys     />} />
        <Route path="model"       element={<ModelStatus />} />
        <Route path="analytics"   element={<Analytics   />} />
        <Route path="settings"    element={<Settings    />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <OnboardingProvider>
          <AppRoutes />
        </OnboardingProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
