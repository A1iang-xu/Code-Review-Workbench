import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

/**
 * 全局 ErrorBoundary — 捕获子组件 render 期抛错，避免整页白屏。
 *
 * 注意：React ErrorBoundary 只捕获 render 期错误，
 * 不捕获事件处理器、setTimeout、异步请求中的错误（那些由 api.ts 拦截器处理）。
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('[ErrorBoundary] 捕获未处理错误:', error, errorInfo);
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: undefined });
  };

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 p-8">
        <div className="max-w-md rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-100">
            <svg className="h-6 w-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h1 className="mb-2 text-xl font-bold text-slate-800">页面渲染出错</h1>
          <p className="mb-4 text-sm text-slate-600">
            应用遇到了一个未处理的错误。可以尝试重试，或返回首页。
          </p>
          {this.state.error && (
            <pre className="mb-4 max-h-32 overflow-auto rounded bg-slate-100 p-2 text-xs text-slate-700">
              {this.state.error.message}
            </pre>
          )}
          <div className="flex gap-2">
            <button
              onClick={this.handleReset}
              className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              重试
            </button>
            <button
              onClick={() => { window.location.href = '/'; }}
              className="rounded border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              返回首页
            </button>
          </div>
        </div>
      </div>
    );
  }
}
