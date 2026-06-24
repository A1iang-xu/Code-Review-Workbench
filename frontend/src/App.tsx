import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { Dashboard } from './pages/Dashboard';
import { ReviewCreate } from './pages/ReviewCreate';
import { ReviewDetail } from './pages/ReviewDetail';
import { SkillManager } from './pages/SkillManager';
import { Settings } from './pages/Settings';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30000,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="min-h-screen bg-slate-50">
          <Sidebar />
          <div className="ml-60">
            <Header />
            <main className="p-8">
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/reviews/new" element={<ReviewCreate />} />
                <Route path="/reviews/:taskId" element={<ReviewDetail />} />
                <Route path="/skills" element={<SkillManager />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="*" element={
                  <div className="flex items-center justify-center h-full">
                    <div className="text-center">
                      <h1 className="text-2xl font-bold text-slate-800">404</h1>
                      <p className="text-slate-500 mt-2">页面不存在</p>
                    </div>
                  </div>
                } />
              </Routes>
            </main>
          </div>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
