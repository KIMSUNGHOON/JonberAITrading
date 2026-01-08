/**
 * Error Boundary Component
 * Catches React errors and displays a fallback UI.
 */

import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: string;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: '' };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: '' };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('React Error Boundary caught an error:', error, errorInfo);
    this.setState({
      errorInfo: errorInfo.componentStack || '',
    });
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-gray-900 text-white p-8">
          <div className="max-w-2xl mx-auto">
            <h1 className="text-2xl font-bold text-red-500 mb-4">
              Something went wrong
            </h1>
            <div className="bg-gray-800 rounded-lg p-4 mb-4">
              <h2 className="font-semibold mb-2">Error:</h2>
              <pre className="text-sm text-red-400 whitespace-pre-wrap">
                {this.state.error?.message}
              </pre>
            </div>
            {this.state.errorInfo && (
              <div className="bg-gray-800 rounded-lg p-4 mb-4">
                <h2 className="font-semibold mb-2">Component Stack:</h2>
                <pre className="text-xs text-gray-400 whitespace-pre-wrap overflow-auto max-h-64">
                  {this.state.errorInfo}
                </pre>
              </div>
            )}
            <button
              onClick={() => window.location.reload()}
              className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg"
            >
              Reload Page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
