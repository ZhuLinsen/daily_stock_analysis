import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ThemeProvider } from './components/theme/ThemeProvider'

/**
 * 静态数据穿透：React 挂载前拦截本地 GET 请求。
 * GitHub Pages 无后端时，防止组件 fetch 失败卡 Loading 或跳到登录页。
 */
const initialData = (window as unknown as Record<string, unknown>).__INITIAL_DATA__;
if (typeof window !== 'undefined' && initialData) {
  const staticData = initialData as Record<string, unknown>
  console.log('[静态穿透] 检测到离线数据，启用 API 拦截')

  const originalFetch = window.fetch.bind(window)

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method !== 'GET') {
      return originalFetch(input, init)
    }

    const urlStr =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : input.url

    // 无后端静态部署时直接返回 auth 通过，避免卡死在登录页
    if (urlStr.includes('/auth/')) {
      return new Response(
        JSON.stringify({ authEnabled: false, loggedIn: true }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      )
    }

    // 拦截 /api/<endpoint>，按端点名映射数据切片
    const match = urlStr.match(/\/api\/([^/?#]+)/)
    if (match) {
      const endpoint = match[1]
      const payload = staticData[endpoint] ?? staticData
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }

    return originalFetch(input, init)
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </StrictMode>,
)
