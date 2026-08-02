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

const isDesktopRuntime = Boolean((window as Window & { dsaDesktop?: unknown }).dsaDesktop)

if ('serviceWorker' in navigator && import.meta.env.PROD && !isDesktopRuntime) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/service-worker.js');
  })
} else if ('serviceWorker' in navigator && isDesktopRuntime) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.getRegistrations().then((registrations) =>
      Promise.all(registrations.map((registration) => registration.unregister())),
    )
    if ('caches' in window) {
      void caches.keys().then((keys) => Promise.all(keys.map((key) => caches.delete(key))))
    }
  })
}
