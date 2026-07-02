import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { ErrorBoundary } from './components/common/ErrorBoundary';
import { LoadingSpinner } from './components/common/LoadingSpinner';

// 路由懒加载 — Monaco Editor 等重组件按需加载，显著降低首屏体积
const Dashboard = lazy(() => import('./pages/Dashboard').then(m => ({ default: m.Dashboard })));
const ReviewCreate = lazy(() => import('./pages/ReviewCreate').then(m => ({ default: m.ReviewCreate })));
const ReviewDetail = lazy(() => import('./pages/ReviewDetail').then(m => ({ default: m.ReviewDetail })));
const SkillManager = lazy(() => import('./pages/SkillManager').then(m => ({ default: m.SkillManager })));
const Settings = lazy(() => import('./pages/Settings').then(m => ({ default: m.Settings })));

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
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <div className="min-h-screen bg-slate-50">
            <Sidebar />
            <div className="ml-60">
              <Header />
              <main className="p-8">
                <ErrorBoundary>
                  <Suspense fallback={<LoadingSpinner />}>
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
                            <a
                              href="/"
                              className="inline-block mt-4 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
                            >
                              返回首页
                            </a>
                          </div>
                        </div>
                      } />
                    </Routes>
                  </Suspense>
                </ErrorBoundary>
              </main>
            </div>
          </div>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
