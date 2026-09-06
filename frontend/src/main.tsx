import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import AppErrorBoundary from './components/AppErrorBoundary'
import { AuthProvider } from './auth/AuthContext'
// Initialise i18next (side-effect import) before <App /> mounts so the first
// render already uses the detected language and <html lang="…"> is correct.
import './i18n'
import './index.css'
import './mobile.css'
import './theme-fix.css'
import './cinematic-inputs.css'
import './cinematic-stages.css'
import './noscroll-layout.css'
import './nexus-cinema.css'
import './cinematic-console.css'

// Apply saved theme before first paint to avoid flash
if (localStorage.getItem('theme') === 'light') {
  document.documentElement.classList.add('light')
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 60_000,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <AppErrorBoundary>
            <App />
          </AppErrorBoundary>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
