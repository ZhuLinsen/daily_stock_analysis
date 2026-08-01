import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ThemeProvider } from './components/theme/ThemeProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </StrictMode>,
)

// Register the Phase 1 PWA Service Worker (issue #2137).
//
// Conditions:
//   - Only register in production builds. Vite dev server already serves
//     source files with HMR; installing the SW there would intercept
//     module requests and break hot reload. The dev-server shell is also
//     not the same as the production built shell, so caching it would be
//     misleading.
//   - Only register in secure contexts (HTTPS or localhost). Service
//     Workers are not available in insecure contexts; attempting to
//     register there throws a console error and is a poor experience.
//
// Failures are logged but never crash the app — PWA installability is a
// progressive enhancement; the SPA itself must keep working without it.
if ('serviceWorker' in navigator) {
  const isProduction = import.meta.env.PROD
  const isSecureContext =
    typeof window !== 'undefined' &&
    (window.isSecureContext ||
      window.location.hostname === 'localhost' ||
      window.location.hostname === '127.0.0.1')
  if (isProduction && isSecureContext) {
    window.addEventListener('load', () => {
      navigator.serviceWorker
        .register('/sw.js', { scope: '/' })
        .catch((err) => {
          console.warn('[dsa-pwa] service worker registration failed:', err)
        })
    })
  }
}

