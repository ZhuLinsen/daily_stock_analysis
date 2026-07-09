# 四大師視角補充（Four Masters Commentary）

個股完整報告的可選補充段（Phase 25.6）：以四個具名投資框架對主報告做**模擬點評**，
豐富多視角觀點。它只能支持、質疑或補充原始報告，**不輸出任何操作行動、
不覆蓋原始 `operation_advice` / `trend_prediction` / `sentiment_score` / 買賣區間**。

> 本功能為投資框架模擬點評，不代表任何人物本人觀點。

## 啟用方式

```bash
# .env（預設開啟；設為 false 可關閉）
ENABLE_FOUR_MASTERS_COMMENTARY=true
```

> Phase 25.6/25.6R 以預設關閉的方式驗證此功能；操作者於 Phase 25.7 review 通過
> 後決定將預設值改為開啟，與 `value_network_mermaid` 一致採「opt-out」模式。

啟用後，分析 prompt（`GeminiAnalyzer` 直呼叫與 Agent 模式兩條路徑）會要求 LLM 在
最上層 JSON 額外輸出 `four_masters_commentary` 物件；設為 `false` 時 prompt、輸出
與報告與功能上線前完全一致。

## 四個視角

| 鍵 | 標題 | 聚焦 |
| --- | --- | --- |
| `buffett` | 巴菲特視角：價值與安全邊際 | 價值、護城河、安全邊際、股價波動是否被誤當成價值受損 |
| `munger` | 蒙格視角：反向思考與誤判檢查 | 反演、誤判心理、最強失效模式、主報告是否被近期價格行為驅動 |
| `duan_yongping` | 段永平視角：生意模式與用戶價值 | 生意模式、產品/用戶價值、長期持有條件、生意品質是否真的改變 |
| `li_lu` | 李錄視角：長期確定性與風險紅線 | 長期確定性、下行保護、風險紅線、論點失效條件 |

另有 `synthesis` 綜合觀察：主要分歧、對原始報告最有用的補充、對原結論信心的影響
（raise/lower/unchanged，僅供參考），以及恆為 `true` 的
`does_not_override_original_action` 保證欄位。

## 資料流

1. **Prompt**：`src/services/four_masters_commentary.build_four_masters_prompt_sections`
   產生 schema 欄位與指示段，注入 `GeminiAnalyzer`（`src/analyzer.py`）與 Agent 模式
   （`src/agent/executor.py`）的既有佔位符（與 `value_network_mermaid` 同路徑）。
2. **解析**：`_parse_response`（direct）與 pipeline agent 路徑把最上層
   `four_masters_commentary` dict 帶進 `AnalysisResult`（非 dict 一律丟棄為 None）。
3. **持久化**：`AnalysisResult.to_dict()` → `raw_result` → 歷史記錄；
   `HistoryService._rebuild_analysis_result` 讀回。
4. **渲染**：`render_four_masters_markdown` 在完整報告（`_generate_single_stock_markdown`）
   插入「## 四大師視角補充」段（位於價值網路附錄之前），結尾附免責聲明。

## 安全邊界（`validate_four_masters_commentary` 強制）

- **欄位白名單**：LLM 夾帶的任何行動類欄位（如 `operation_advice`、`final_action`、
  `buy_zone`）一律剝除；渲染端不信任 LLM 提供的 title。
- **枚舉收斂**：`supports_original_view` 非法值 → `mixed`；`confidence_adjustment`
  非法值 → `unchanged`。
- **`does_not_override_original_action` 恆為 True**，不採信 LLM 值。
- **淨化**：去 HTML 標籤與角括號、去控制字元、單欄位長度上限 600 字、
  紅線清單上限 5 條——渲染不引入不安全 HTML。
- **安全降級**：整段缺失、非 dict、或所有視角皆無 `summary` 時返回 None，
  報告不出現該段、不影響其他內容；舊報告（無此欄位）渲染完全不變。
- ETF / 槓桿型 ETF：prompt 指示以工具屬性（追蹤品質、費用、槓桿衰減）評論，
  不杜撰個別公司經營細節。

## 測試

`tests/test_four_masters_commentary.py`（23 例）：schema roundtrip、prompt 旗標
gating（兩條路徑）、驗證器（枚舉收斂/行動剝除/HTML 淨化/超長裁剪/畸形降級）、
Markdown 渲染（含免責聲明、無不安全 HTML、英文版）、完整報告插入與降級、
原始欄位不被變更。

## Web 結構化 UI（Phase 25.7）

`apps/dsa-web` 在既有報告卡片視覺語言之上，為 `raw_result.four_masters_commentary`
新增一個結構化區塊，取代純 Markdown 呈現：

- **Adapter**：`src/components/report/visual/fourMastersCommentaryAdapter.ts`——
  把 API 回傳的 camelCase（容忍 snake_case）payload 正規化為嚴格的 View Model；
  欄位白名單、枚舉收斂（`support`/`challenge`/`mixed`、`raise`/`lower`/`unchanged`）、
  HTML/控制字元淨化、長度裁剪（600 字/欄、紅線 5 條）與後端驗證器同構；任何缺失、
  非物件、或全視角皆無 `summary` 的 payload 一律回傳 `null`（區塊整段不渲染）。
- **元件**：`src/components/report/visual/FourMastersCommentarySection.tsx`——
  四張具名視角卡（含立場徽章、細項、僅李錄卡片顯示的紅線清單）+ 一張綜合觀察卡
  （信心調整標籤）+ 固定免責聲明；全部為純文字節點（無 `dangerouslySetInnerHTML`），
  桌面 `sm:grid-cols-2` 網格、行動裝置單欄堆疊。
- **去重**：`ReportMarkdownPanel.tsx` 偵測到結構化 payload 有效時，會從渲染的
  Markdown 中剝除對應的「## 四大師視角補充」段落（含其 `###` 子段與免責聲明），
  改由結構化 UI 顯示於同一位置，避免同一內容出現兩次；不影響其他 Markdown 段落。
  舊報告（無 `four_masters_commentary`）Markdown 渲染完全不變。
- **測試**：`fourMastersCommentaryAdapter.test.ts`（8 例）、
  `FourMastersCommentarySection.test.tsx`（7 例）、`ReportMarkdownPanel.test.tsx`
  新增 3 例（結構化渲染去重、缺結構化 payload 時保留 Markdown、舊報告不變）。
- **Playwright**：`e2e/four-masters-commentary.spec.ts`——資料驅動（從本地歷史記錄
  探測含 `four_masters_commentary` 的股票/ETF 報告與一份舊報告），驗證結構化區塊
  渲染、無重複段落、行動視口單欄堆疊且無橫向溢出；本地無符合資料時安全跳過。
