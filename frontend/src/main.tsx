import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import { AuthProvider } from './auth/AuthContext'
import { App } from './App'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A live kitchen ops tool: stale data on a phone under bad wifi is
      // worse than a slightly-too-frequent refetch, but we don't need to
      // hammer the API either.
      staleTime: 15_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
