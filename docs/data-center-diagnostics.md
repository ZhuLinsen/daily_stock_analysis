# 数据中心

Web 数据中心位于 `/data`，用于只读查看数据源能力、数据集质量与运行时优先级。页面只消费 `GET /api/v1/data/overview`，不读取系统配置原始值，也不自行拼接 screening、provider 或配置探针。

## 页面内容

- Provider 能力：卡片展示运行状态及 `dataset_markets` 给出的精确数据集/市场支持关系；页面顶部汇总已配置的 Provider 数量，不在卡片中单独展示 enabled/configured 标志。
- 数据集质量：`ok`、`degraded`、`partial`、`unconfigured`、`unavailable`、`unknown`、`stale`，以及当前来源、最近成功时间和脱敏诊断。
- 路由优先级：每个运行场景的 provider 顺序及其配置来源。
- Overview warnings：接口认为需要关注、但不应阻断其他块展示的警告代码。

## 状态边界

- 页面不会根据“已知 provider 名称”把冷启动状态推断为 `ok`；后端返回 `unknown` 时原样展示。
- 页面不会把 Provider 的 `markets` 与 `datasets` 计算笛卡尔积；精确支持范围以 `dataset_markets` 为准。
- 多市场数据集使用不同 provider 时，顶层 `source` 合法地为空；页面会读取 `coverage.markets`，按市场展示实际来源，而不是显示成 `--`。
- Overview 请求失败时整页显示可重试错误；接口成功但 provider/dataset 均为空时显示 empty 状态。
- 单个 provider 或 dataset 的 `partial`、`unknown`、`stale`、`unavailable` 只影响对应条目，其余条目继续展示。

## 安全边界

该页面不调用 `/api/v1/system/config`，不展示 API Key、Token、Cookie 或原始环境变量。需要修改配置时仅跳转到 Settings，由现有配置脱敏和权限边界负责处理。

## 验证与回滚

前端测试使用与 `DataCapabilityOverviewResponse` 同形的 payload，覆盖 success、cold-start unknown、warning、empty、error 和 retry。回滚页面时可移除 `/data` 路由、导航、API/type、页面及文档；后端 capability 契约不受影响。

## 浏览器验收

`cd apps/dsa-web && npx playwright test --config playwright.fixture.config.ts` 使用固定 API fixture 渲染真实页面，不依赖后端服务或密钥。CI 的 `web-gate` 安装 Chromium、执行验收，并将截图上传为 `web-ui-evidence-<head SHA>` artifact（保留 30 天）；截图不提交到仓库。该验收验证页面交互和展示，不代表实时 provider/LLM 可用性。

桌面导航在短窗口中仅滚动链接列表，主题、语言与退出控件保留在可见区域；主题菜单不进入滚动裁剪容器。浏览器验收包括 1280×720、认证与选股均开启时的设置/退出可达性、主题菜单及取消退出。
