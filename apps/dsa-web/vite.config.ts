import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

const packageJson = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf-8'),
) as { version?: string }
const buildTime = new Date().toISOString()

const vendorChunkByPackage: Record<string, string> = {
  react: 'vendor-react',
  'react-dom': 'vendor-react',
  scheduler: 'vendor-react',
  'react-router': 'vendor-router',
  'react-router-dom': 'vendor-router',
  motion: 'vendor-motion',
  'framer-motion': 'vendor-motion',
  'motion-dom': 'vendor-motion',
  'motion-utils': 'vendor-motion',
  'lucide-react': 'vendor-icons',
  recharts: 'vendor-charts',
  'victory-vendor': 'vendor-charts',
  '@reduxjs/toolkit': 'vendor-charts',
  'decimal.js-light': 'vendor-charts',
  'es-toolkit': 'vendor-charts',
  eventemitter3: 'vendor-charts',
  immer: 'vendor-charts',
  'react-redux': 'vendor-charts',
  reselect: 'vendor-charts',
  'tiny-invariant': 'vendor-charts',
  'use-sync-external-store': 'vendor-charts',
  // Markdown renderer dependencies that are not covered by prefix rules below.
  'react-markdown': 'vendor-markdown',
  unified: 'vendor-markdown',
  vfile: 'vendor-markdown',
  'remove-markdown': 'vendor-markdown',
  bail: 'vendor-markdown',
  'comma-separated-tokens': 'vendor-markdown',
  'decode-named-character-reference': 'vendor-markdown',
  devlop: 'vendor-markdown',
  'html-url-attributes': 'vendor-markdown',
  'property-information': 'vendor-markdown',
  'space-separated-tokens': 'vendor-markdown',
  'trim-lines': 'vendor-markdown',
  'vfile-message': 'vendor-markdown',
}

const vendorChunkByPackagePrefix: Array<[string, string]> = [
  ['d3-', 'vendor-charts'],
  ['remark-', 'vendor-markdown'],
  ['micromark', 'vendor-markdown'],
  ['mdast-util-', 'vendor-markdown'],
  ['hast-util-', 'vendor-markdown'],
  ['unist-util-', 'vendor-markdown'],
]

const getVendorPackageName = (id: string): string | undefined => {
  const normalizedId = id.replace(/\\/g, '/')
  const marker = '/node_modules/'
  const markerIndex = normalizedId.lastIndexOf(marker)
  if (markerIndex === -1) {
    return undefined
  }

  const packagePath = normalizedId.slice(markerIndex + marker.length)
  const [firstSegment, secondSegment] = packagePath.split('/')
  if (!firstSegment) {
    return undefined
  }

  if (firstSegment.startsWith('@')) {
    return secondSegment ? `${firstSegment}/${secondSegment}` : undefined
  }

  return firstSegment
}

const getVendorChunkName = (id: string): string | undefined => {
  const packageName = getVendorPackageName(id)
  if (!packageName) {
    return undefined
  }

  return (
    vendorChunkByPackage[packageName]
    ?? vendorChunkByPackagePrefix.find(([prefix]) => packageName.startsWith(prefix))?.[1]
    ?? 'vendor'
  )
}

// https://vite.dev/config/
export default defineConfig({
  define: {
    __APP_PACKAGE_VERSION__: JSON.stringify(packageJson.version ?? '0.0.0'),
    __APP_BUILD_TIME__: JSON.stringify(buildTime),
  },
  plugins: [
    tailwindcss(),
    react({
      babel: {
        plugins: [['babel-plugin-react-compiler']],
      },
    }),
  ],
  server: {
    host: '0.0.0.0',  // 允许公网访问
    port: 5173,       // 默认端口
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // 打包输出到项目根目录的 static 文件夹
    outDir: path.resolve(__dirname, '../../static'),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: getVendorChunkName,
      },
    },
  },
})
