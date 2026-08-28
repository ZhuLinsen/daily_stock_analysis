# DSA Design System

DSA 使用「Warm Trade」视觉语言：这是一套 Futu-inspired、但不复制富途品牌资产或界面结构的金融工作台配色。暖白与石墨黑承载高密度信息，橙色只承担主行动与当前状态，行情与风险继续使用明确的红绿状态色。目标是专业、聚焦、耐看，而不是把品牌色铺满页面。

## Color

颜色分三层使用：原始色板只定义颜色；语义 Token 描述用途；组件只能消费语义 Token。

| Token | 用途 | Light | Dark |
| --- | --- | --- | --- |
| `--ds-brand` | 主操作、选中、链接 | Deep Trading Orange | Bright Trading Orange |
| `--ds-brand-soft` | 选中底、轻提示 | Warm Orange 50 | Warm Orange 950 |
| `--ds-brand-foreground` | 品牌色上的文字 | White | Graphite 950 |
| `--ds-support` | 少量辅助信息 | Graphite 600 | Graphite 300 |
| `--ds-canvas` | 页面底色 | Warm Gray 50 | Graphite 975 |
| `--ds-panel` | 卡片、侧栏、工具条 | Warm White | Graphite 925 |
| `--ds-panel-muted` | 次级区域、表头、悬停 | Warm Gray 100 | Graphite 875 |
| `--ds-text` | 主文本 | Graphite 950 | Warm Gray 50 |
| `--ds-text-secondary` | 说明、元数据 | Graphite 600 | Graphite 300 |
| `--ds-border` | 默认边框与分割线 | Warm Gray 250 | Graphite 750 |

规则：主色占比不超过界面的 8%；橙色只用于主操作、焦点、当前导航和少量关键标记；正文不可使用强调色；红绿只表达行情或状态；禁止在组件里新增十六进制或固定 HSL。

## Surface

表面只有三个层级：Canvas、Panel、Muted Panel。常规 Panel 使用不透明背景和 1px 边框，不使用模糊；悬停通过边框或背景变化反馈，不通过上浮阴影。

- Canvas：页面背景。
- Panel：主卡片、侧栏、弹层和工具条。
- Muted Panel：选项、表头、代码区和局部强调。
- Overlay：仅用于抽屉遮罩，不作为内容背景。

## State

| Token | 语义 | 禁止用途 |
| --- | --- | --- |
| `--ds-positive` | 成功、正向行情 | 普通装饰 |
| `--ds-caution` | 提醒、等待、需关注 | 主操作按钮 |
| `--ds-negative` | 错误、风险、负向行情 | 普通标签 |
| `--ds-focus` | 键盘焦点环 | 静态边框 |

状态不能只依赖颜色，必须同时提供文字、图标或形状。中国市场行情保持红涨绿跌，其余成功/失败语义使用绿/红。

## Spacing

使用 4px 基准：`4 / 8 / 12 / 16 / 24 / 32`。页面主栅格间距 12px，卡片内边距 12–16px，表单控件高度 32–40px。不得用负间距修正视觉错位。

圆角层级：控件 6–8px，卡片 10–12px，模态框 12–16px。同一层级内保持一致。

## Component

- Button：每个区域只保留一个 Primary；Secondary 使用中性底色；Danger 仅用于不可逆动作。
- Card：使用 Panel 背景、默认边框和零阴影；卡片内部优先用分割线，不再嵌套卡片。
- Tabs：选中态使用 `--ds-brand-soft` 背景与主色文本，尺寸不得因状态变化。
- Table：表头使用 Muted Panel；数字右对齐或使用等宽字体；涨跌色只作用于值。
- Input：默认边框使用 `--ds-border`；聚焦使用 `--ds-focus`，不改变控件尺寸。
- Badge：默认中性；Info 使用 Brand；状态 Badge 使用对应 State Token。
- Navigation：当前项使用暖橙浅底与橙色图标，不使用左侧发光条或阴影。

## Accessibility

正文与背景目标对比度至少 4.5:1，大文本与非文本控件至少 3:1。键盘焦点始终可见；深浅主题分别验收，不通过简单反色推导状态色。

## Migration

现有 Tailwind Token（如 `primary`、`card`、`border`）继续作为兼容层，但其值必须来自 `--ds-*`。新增组件不得引用 `--home-*` 或写死颜色；页面专用 Token 应逐步收敛到语义层。
