# PWA 支持（Phase 1 — 离线壳缓存）

> 关联：Issue #2137 — DSA Web 前端 PWA 增强
> 状态：Phase 1 已合入（manifest + service worker + 图标）
> 后续：Phase 2 — 行情/估值接口的 Background Sync 与离线只读模式（不在本 PR）

## 概述

DSA Web 前端现在可以作为 PWA 安装到桌面/手机主屏。本 Phase 1 的目标仅是
**可安装 + 离线壳可用**，不缓存任何业务数据。

## 触发场景

- 桌面浏览器地址栏右侧出现「安装」按钮（Chrome / Edge）
- iOS Safari「分享 → 添加到主屏幕」
- Android Chrome「添加到主屏幕」

## 安装后行为

- 应用以独立窗口启动（无浏览器地址栏）
- 主屏图标来自 `apps/dsa-web/public/icon-192.png` / `icon-512.png`
- 应用启动主题色 `#0f172a`（与 DSA 暗色主题一致；与 `manifest.webmanifest`
  和 `index.html` 中 `<meta name="theme-color">` 保持一致）

## 离线行为（重要）

| 资源类型                 | 离线可用 | 备注                                                |
| ------------------------ | -------- | --------------------------------------------------- |
| 入口 HTML 壳             | ✅       | network-first，失败 fallback cached shell            |
| 静态资源（含 `/assets/*` 哈希 bundle）| ✅ | install 时 fetch `/` 解析当前部署 `/assets/*` bundle 预缓存；运行时 SWR 刷新 |
| 离线 fallback           | ✅       | `/offline.html`（SW install 时合成，cache.put 写入）|
| `/api/*`                | ❌       | 永远走网络，不缓存                                  |
| `/auth/*`               | ❌       | 永远走网络，不缓存                                  |
| `/login`                | ❌       | 永远走网络，不缓存                                  |
| `/logout`               | ❌       | 永远走网络，不缓存                                  |
| `/stocks.index.json`    | ❌       | 永远走网络，不缓存（即使带 `?_t=<ts>` cache-bust） |
| 跨域资源                | n/a      | 不接管，浏览器默认处理                              |

注：哈希 JS/CSS bundle 文件名每次 build 都变，install 时不写死 URL 列表；
SW install 阶段 `fetch('/')` 后解析返回 HTML 中实际引用的
`<script type="module" src="/assets/...">`、`<link rel="stylesheet" href="/assets/...">`
与 `<link rel="modulepreload" href="/assets/...">`，把当前部署真正引用的 bundle
一次性 precache 到 cache storage。这样首次在线访问 + SW install 完成后立刻
离线 relaunch，不需要 worker 先控制过一次页面请求就能拿到 bundle。运行时
再 SWR 刷新这些 bundle 的新 hash 版本。

## 设计契约

### Service Worker 缓存边界（绝对红线）

**永远不缓存任何鉴权 / 实时数据接口**。理由：

1. **时效性** — 行情、估值、报告数据均带时间戳；缓存会返回旧值，
   而用户无从感知这是缓存，可能据此做出错误决策。
2. **安全** — `/api/*`、`/auth/*` 的 Response 可能携带 `Set-Cookie`。
   即便我们 stripped，缓存仍可能跨用户串号。
3. **可观测性** — 财务数据出问题需要立刻定位；缓存层会让排障复杂化。

具体实现见 `apps/dsa-web/public/sw.js`。代码中以 deny-list（`/api/`、
`/auth/`、`/login`、`/logout`）显式拒绝缓存。

### 注册条件

Service Worker **只在生产构建 + 安全上下文**注册：

- `import.meta.env.PROD` — dev server 上的 SW 会破坏 HMR
- `window.isSecureContext` — 非 HTTPS（或非 localhost）SW 不可用

详见 `apps/dsa-web/src/main.tsx`。

## 验证步骤

### 1. 单元/手动验证

```bash
cd apps/dsa-web
npm run dev
# 浏览器打开 http://localhost:5173
# 注：localhost 是 secure context 例外，SW 可在 http 下注册；
#   非 localhost 的非 HTTPS 环境（如 LAN IP）SW 不可用。
# 1. DevTools → Application → Service Workers：不应有 SW 注册（dev 模式不注册）
# 2. Network → 强制 Disable cache：所有请求应正常 200

npm run build && npm run preview
# 1. DevTools → Application → Service Workers：应有 SW 处于 activated
# 2. DevTools → Application → Cache Storage：应有 dsa-shell-v1
# 3. DevTools → Application → Manifest：应正确解析
```

### 2. 离线 fallback 验证

1. 在已加载页面时 DevTools → Network → Throttling 切到 Offline
2. 刷新页面：应看到 `/offline.html` 的友好降级提示
3. 检查请求：导航请求 `event.respondWith` 应返回 `/index.html` 缓存，
   然后才 fallback 到 `/offline.html`

### 3. 鉴权边界验证

```bash
# 打开 Network，勾选 Preserve log
# 在 dev/preview 中登录一次
# DevTools → Application → Cache Storage → dsa-shell-v1
# 应该看不到 /api/、/auth/、/login 任何条目
```

### 4. PWA 清单合规

```bash
# Chrome DevTools → Application → Manifest
# - name / short_name / start_url / display / theme_color / background_color
# - icons 必须有 192×192 和 512×512，且 purpose 包含 "any"
# Chrome DevTools → Lighthouse → PWA category
# - Installable: 应通过
```

## 已知的非目标

- **Phase 1 不缓存任何 API 数据**。Phase 2（独立 issue）才会引入：
  - 行情数据 IndexedDB 缓存（TTL 短）
  - 估值报告离线只读模式
  - Background Sync 拉新数据

- **不引入消息推送**。这是另一个独立能力，与 PWA 缓存解耦。

## 故障排查

| 现象                        | 原因                              | 处置                                |
| --------------------------- | --------------------------------- | ----------------------------------- |
| DevTools 显示「已注册」但没生效 | 注册后页面没刷新                  | 关闭所有标签重新打开                |
| `register failed` 警告      | 非 HTTPS / 非 localhost           | 部署到 HTTPS，或仅在 localhost 测试  |
| `/offline.html` 没出现      | cache.put 失败或路径不一致        | 检查 sw.js 中 `OFFLINE_HTML` 与 `SHELL_ASSETS` |
| Lighthouse 显示「PWA 不合格」 | 缺图标 / 缺 theme-color           | 检查 `public/` 下是否有所有图标     |
