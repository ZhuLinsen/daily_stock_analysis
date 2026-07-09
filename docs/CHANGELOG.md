# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

> For user-friendly release highlights, see the [GitHub Releases](https://github.com/ZhuLinsen/daily_stock_analysis/releases) page.

## [Unreleased]

- [改進] 「四大師視角補充」功能預設值由關閉改為開啟（`ENABLE_FOUR_MASTERS_COMMENTARY` 預設 `true`，與 `value_network_mermaid` 一致採 opt-out 模式；設為 `false` 可關閉）。

- [新功能] Web 完整分析報告新增結構化「四大師視角補充」UI（`FourMastersCommentarySection`）：當歷史紀錄的 `raw_result.four_masters_commentary` 存在且通過前端驗證時，於報告內容區顯示巴菲特/蒙格/段永平/李錄四張卡片與綜合觀察卡，桌面為 2x2 網格、行動裝置單欄堆疊；會抑制對應的 Markdown 版重複段落，避免同一內容出現兩次；不新增任何買賣操作按鈕、不採信 LLM 夾帶的行動類欄位，畸形或缺失資料時安全降級為不顯示；沿用既有報告卡片視覺語言，未修改原始評分/趨勢/操作建議欄位。

- [新功能] 個股完整報告新增可選「四大師視角補充」段（`ENABLE_FOUR_MASTERS_COMMENTARY=true` 啟用，預設關閉）：以巴菲特/蒙格/段永平/李錄四個投資框架對主報告做模擬點評（支持/質疑/部分支持），僅為評論補充，不輸出買賣行動、不覆蓋原始 `operation_advice`/`trend_prediction`/評分/買賣區間；LLM 夾帶的行動欄位會在驗證時剝除，缺失或畸形時報告安全降級不出段。詳見 `docs/four-masters-commentary.md`。

- [改進] 台股日報 `market_review` 生成時新增 FinMind 結構化快照，包含 006208、0050/006208/2330 價格變化、成交量/成交金額、PER/PBR/殖利率可用性、資料缺口與台股語意方向 metadata，供後續閱讀版面直接消費。

- [改進] 台股日報改為結構化閱讀版面，將既有 FinMind `market_review` 報告分區呈現為今日重點、主要指數、法人資金、融資融券、代表標的與資料狀態，舊版不完整 Markdown 仍保留安全 fallback。

- [改進] Web 將既有 FinMind 台股市場日報入口與狀態文案由「市場概覽」改名為「台股日報」，與「美股日報」形成成對日報入口；內部 `market_review` API/配置識別維持不變。

- [修復] 問股頁 Google Finance helper 在輸入股票代號時即時顯示，且即使瀏覽器阻擋剪貼簿複製，仍會開啟可解析標的的 Google Finance 外部頁。

- [改進] Google Finance 外部參考入口移至個股分析主介面工具列，完整報告內不顯示該入口；連結仍使用 persisted metadata/exchange resolver，未知交易所維持隱藏。

- [改進] Google Finance 外部參考改為使用台美標的 metadata/exchange resolver 產生連結，美股不再依賴前端 ticker-level mapping；未知交易所維持隱藏連結、不猜測。

- [新功能] Web 個股分析工具列與問股頁新增 Google Finance 外部參考入口，可開啟已知 TW/US 標的的 Google Finance quote 頁並複製研究問題提示；不抓取、不嵌入、不自動提交 Google 內容。

- [新功能] 完整分析報告新增直接下載 PDF 功能，後端以列印專用報告頁產生完整 PDF 檔。

- [改進] 優化市場恐慌指標卡片的視覺排版與官方指標 marker，移除「原始標籤」冗餘文字，讓個股分析與完整報告中的 VIX／VIXTWN 與「系統評分」更清楚可讀。

- [改進] 恐慌指標卡 UI polish：個股分析側欄改為半圓雙指針 gauge，完整報告保留橫向雙指針 meter；VIX/VIXTWN 與「系統評分」各自顯示狀態 tag、日期與 info 說明，並修正 tooltip 重複/重疊問題。

- [新功能] 完整報告與分析儀表板改為單一雙指針恐慌指標卡，同時顯示市場恐慌指數（美股 VIX／台股 VIXTWN）與「系統評分」，並顯示指標日期與 hover 說明。

- [修復] 將完整報告與儀表板中的內部情緒分數標籤改為「系統評分」，並補充 hover 說明其為本系統分析分數、非市場官方指數、非 VIX/VIXTWN，避免與正式恐慌指數混淆。

- [修復] 將完整報告與儀表板中的內部情緒分數標籤改為「系統評分」，並補充 hover 說明其為本系統分析分數、非市場官方指數、非 VIX/VIXTWN，避免與正式恐慌指數混淆。

- [修復] 將完整報告與儀表板中的內部情緒分數標籤改為「系統評分」，並補充 hover 說明其為本系統分析分數、非市場官方指數、非 VIX/VIXTWN，避免與正式恐慌指數混淆。
- [修復] 台股/台股 ETF 完整報告的市場風險卡在無 VIX 快照但已有分析情緒分數時，改顯示「市場情緒 · 恐慌貪婪分數」與既有儀表板分數，避免將內部情緒分數誤標為 VIX 或顯示誤導性的「VIX 資料不足」。
- [新功能] 完整分析報告 K-line 圖表新增 1D/5D 盤中 snapshot 分頁，抽屜分頁調整為 1D/5D/1M/3M/1Y（隱藏 1W UI、保留後端相容），盤中分頁讀取報告保存的 `/kline` snapshot、不顯示日線 MA，並依 `MARKET_REVIEW_COLOR_SCHEME` 套用紅漲綠跌或綠漲紅跌至 K 線與成交量。
- [新功能] 完整分析報告視覺摘要新增 market-aware K-line 圖表：透過新的 `/api/v1/history/{id}/kline` DB/cache 優先端點讀取日線 OHLCV，台股/台股 ETF 保持 FinMind-backed cache 路徑，美股/美股 ETF 保持 yfinance-backed cache 路徑，前端使用 TradingView Lightweight Charts 顯示 K 線、成交量、MA20/60/120/252 與固定 hover 數值列。
- [修復] 修正 US 股票 fresh 分析時 FinancialResultCards 全部顯示「—」的問題：`_build_offshore_fundamental_context` 漏合併 yfinance bundle `valuation` block，`_attach_valuation_fundamental_snapshot` 從 `_build_fundamental_block` 包裝層的頂層而非 `"data"` subkey 讀取數值；同時移除 Visual Summary 中重複的 現價（TechnicalSnapshotCards）與重複的 VIX（KPI row）顯示（Phase 19G-R5B）。
- [改進] WebUI 視覺摘要「估值快照」與「基本面」卡片改為直接顯示投資人關注數值（PE(TTM)/Forward PE/PB/股息率/市值；營收 YoY/淨利 YoY/ROE/毛利率），取代先前以「可用/資料缺口/部分可用/不適用」badge 為主的資料可用性面板；ETF/指數不渲染財務卡片；缺少欄位顯示「—」；資料來源（yfinance/finmind · as_of）以 footnote 形式呈現於各卡片底部（Phase 19G-R5）。
- [改進] WebUI 報告抽屜新增視覺摘要面板（Phase 19G）：在 Markdown 全文之上插入決策卡、VIX gauge、多週期趨勢條、技術指標卡、資料可用性面板與作戰計畫卡；平行 fetch 不阻塞 Markdown 渲染，detail fetch 失敗時靜默降級。
- [新功能] 個股／ETF／指數完整報告新增「📈 多週期趨勢快照」區塊（1週/1月/1季/半年/52週），位於「🌡️ 市場風險溫度計」之後、作戰計劃之前；數值由後端從既有 OHLC 資料決定性計算（漲跌幅、區間高低點、自高點回撤、均線位置、趨勢狀態），52 週區間獨立向資料庫優先的歷史資料載入器請求最多 252 個交易日（不調整既有 89 天技術指標視窗），資料不足的週期顯示「資料不足」而非省略或臆測；LLM 不參與該區塊數值生成；未知類型不顯示。
- [新功能] 完整報告新增「🧭 ETF／指數曝險摘要」（限 ETF/指數）與「🌡️ 市場風險溫度計」（個股／ETF／指數皆顯示，未知類型不顯示）兩個區塊，位於估值與基本面快照之後、作戰計劃之前；美股市場風險溫度計重用既有 `fetcher_manager.get_realtime_quote()` 讀取 VIX/SPX（無新資料源、無新快取，沿用既有 CircuitBreaker），台股本期不發起任何外部資料請求，固定顯示資料不足與原因說明；LLM 不參與該區塊數值生成。
- [新功能] 個股（`instrument_type=stock`）完整報告新增「🧾 估值與基本面快照」區塊，位於資料透視之後、作戰計劃之前；數值由後端決定性組裝（台股使用 FinMind `TaiwanStockPER`/`TaiwanStockMonthRevenue`，美股重用既有 yfinance 基本面資料），LLM 不參與該區塊數值生成；缺失欄位顯示為資料缺口而非省略；ETF/指數/未知類型不顯示此區塊。
- [新功能] 個股完整報告新增可選的「附錄：價值網路圖」Mermaid 流程圖區塊，由新環境變數 `ENABLE_VALUE_NETWORK_MERMAID`（預設 `false`）控制是否在 Prompt 中請求 LLM 產出；後端會驗證圖表型別、長度、節點/分類數量並過濾危險內容，驗證失敗則靜默省略，不影響報告其餘內容；WebUI 以 `mermaid`（`securityLevel: strict`）安全渲染，渲染失敗時顯示提示並保留原始 Mermaid 原始碼。
- [修復] 市場概覽任務完成後會即時更新 MARKET 個股欄卡片與市場概覽歷史資料，完成後不需重新整理整頁即可看到最新市場概覽入口。
- [修復] Route B 相關資訊/新聞納入規則改為台股/美股正向相關性策略：非台美來源詞不再作為台美新聞正向訊號，無台美公司/財務/產業/市場關聯的內容會在進入 context/cache/tool output 前被丟棄，並保留具財務意義的 App/下載/活躍使用者等商業指標新聞。
- [修復] 大盤覆盤的美股區塊在 `report_language=zh_TW`（預設值）時不再強制輸出英文標題與段落（如 `US Market Recap`、`Market Summary`、`Index Commentary`），改為遵循設定語言輸出繁體中文內容；報告內層標題統一為「台股大盤回顧」「美股大盤回顧」，不再出現舊版「大盤覆盤」字樣。
- [修復] 市場概覽歷史記錄/個股欄卡片標題不再顯示「大盤覆盤」（含「大盤覆盤 MARKET」混合標籤），改為「市場概覽」；前端針對 `MARKET` 偽代號的卡片標題額外做防禦性正規化，涵蓋既有舊資料。
- [修復] 問股自由文本輸入中的常見金融縮寫（如 TTM、EBITDA、DCF、PE）與常見英文填充詞不再被誤判為股票代號候選（同步前後端的常見詞排除清單）。
- [修復] GitHub Actions 每日分析工作流讀取 `SEARXNG_BASE_URLS` 時改為 Variables 優先、Secrets 回退，修復僅配置 Variables 時 URL 不生效的問題。
- [改進] 首頁重複任務警示新增關閉按鈕與 5 秒自動消失，避免警示長期佔用版面。
- [修復] Docker 映像預置 efinance 快取目錄（`efinance/data`）屬主給非 root 執行使用者 `dsa`，修復 efinance 資料來源因寫入 `search-cache.json` 觸發 `PermissionError` 而每次抓取失敗降級的問題。
- [修復] 股票代號/名稱查詢中，純大寫英文代號（如 TEAM）不再因前端搜尋僅抑制名稱比對而靜默只顯示台股別名候選；現在會同時列出對應的美股精確比對候選並排序在前。
- [修復] 新增「Global Unichip」「President Chain Store」作為台股創意（3443）、統一超（2912）的英文全名別名。
- [修復] 大盤覆盤交易日檢查改為正確識別台股獨立交易日曆（Asia/Taipei / XTAI），`MARKET_REVIEW_REGION=all` 不再被舊版邏輯誤判轉換成 cn 並因而中止，可正常產生並持久化台股/美股大盤覆盤報告；cn/hk/both 等舊版區域語意維持不變。
- [修復] 市場概覽在無可持久化報告而中止時，前端不再顯示「市場概覽任務已完成，結果已生成並按配置推送」的誤導性成功訊息，改為顯示實際的跳過原因。
- [修復] WebUI/FastAPI 支援明確 opt-in 的 Mac mini LAN runtime：`DSA_ALLOW_EXTERNAL_NETWORK=true` 並使用 `WEBUI_HOST=0.0.0.0` 後可接受 private LAN Host/CORS，同時保留預設 localhost-only 與非 wildcard CORS。
- [修復] 持股混合 TWD/USD 總額改為必須使用有效匯率換算；缺少匯率時顯示不可用警告與分幣別小計，匯率刷新後顯示實際 USD/TWD 換算總額與匯率資訊。
- [修復] Web 持股手工錄入交易、資金流水、公司行為表單新增 TWD/USD 幣別下拉選單，並依選定帳戶基準幣別預設為 TWD 或 USD。
- [修復] 系統設定的大盤覆盤市場改為台股、美股、全部市場（tw/us/all），移除 A 股 / 港股作為活躍選項並同步配置 schema 預設值。
- [修復] Web 個股欄和歷史卡片在窄佈局下不再讓市場階段標籤遮擋股票名稱。
- [修復] 問股自由文字追問不再將 TTM、PE、YOY 等金融縮寫誤識別為新股票程式碼。
- [修復] GitHub Actions 每日分析工作流讀取 SearXNG 自建例項地址時支援 Variables 優先、Secrets 回退，修復僅配置 Variables 時 URL 不生效的問題。
- [改進] Web 首頁側欄不再單獨展示大盤覆盤歷史集合，最新大盤覆盤作為 `MARKET` 併入個股欄，按最近分析時間參與排序，並複用個股欄的選擇、刪除、完整報告與歷史趨勢檢視能力。
- [修復] Web/桌面端左側導航選中態改用 border 實現，避免藍色豎條指示器溢位側欄邊界；側欄展開寬度 116px → 136px，新增 rail 緊湊模式。
- [修復] Windows 桌面端自動更新安裝目錄不再預先加引號，避免帶空格路徑在自動安裝時觸發“缺少快捷方式 / 找不到 Daily Stock Analysis.exe”的系統彈窗。
- [修復] Agent 分析路徑生成 AnalysisContextPack overview 前複用已落庫日線分析上下文，避免日線已抓取成功仍顯示 `daily_bars_missing`。
- [新功能] Web 大盤覆盤報告新增專用展示檢視，歷史入口和首頁即時結果統一使用 Markdown/GFM 渲染並隱藏個股專屬模組。
- [新功能] 大盤覆盤新增結構化 `market_review_payload`，Web、歷史詳情和推送統一基於結構化資料渲染，並保留 Markdown 相容展示。
- [文件] 本次迭代僅重構大盤覆盤展示鏈路（統一 Markdown/GFM 渲染與結構化 payload 渲染），不涉及 `LITELLM_*`、`LLM_*`、`provider/model/base_url` 等執行時配置語義；如需回退採用常規釋出回滾。
- [修復] 修正大盤覆盤結構化 `breadth` 的可用性判斷：當市場不支援/抓取失敗（如美股、港股或 A 股 breadth 不可用）時不下發 `breadth`，前端展示“暫無資料”，避免誤導性 0 值。
- [修復] 明確大盤覆盤語言行為調整為遵循全域性 `report_language`，並在回退場景保持原語種提示（如美股/港股預設會按配置語言展示）；相容性變化說明見該條款，無需額外改動 provider/model/base_url。
- [修復] 美股中文場景下，市場標籤與策略藍圖（`Strategy Blueprint/Strategy Framework`）已本地化為中文顯示，避免 `report_language=zh` 下混入英文策略段落與市場標籤；與 Issue #1555 的歷史/即時結果一致。
- [修復] Docker Web 設定頁讀取配置時在活躍 `.env` 檔案缺項時回退展示啟動注入的同名環境變數，並補清 `env_file` / `--env-file`、`ENV_FILE=/app/data/runtime.env` 與單檔案 `.env` 掛載邊界文件。
- [文件] 補充說明：LLM / LiteLLM 相容鍵的回退僅用於 Settings 介面展示與校驗上下文拼裝，不改寫、不遷移、不清理使用者現有的 provider/model/base URL 持久化配置；未發生 provider / model / base URL 語義遷移，僅保留同名啟動注入的展示級兜底。相容邊界依據 `requirements.txt`（`litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`、`openai>=1.0.0`）；官方語義來源：[LiteLLM OpenAI-compatible](https://docs.litellm.ai/docs/providers/openai_compatible)、[OpenAI Chat Completion API](https://platform.openai.com/docs/api-reference/chat/create)。回退/恢復路徑為：重啟/更新後清理同名 `env_file` / `--env-file` / `environment` 覆蓋後使用持久化儲存值，或透過桌面端匯入/匯出 `.env` 片段恢復；僅在 WebUI 未改寫同名啟動注入值時才會按該片段接管。驗證迴歸點見 `tests/test_system_config_service.py::test_get_config_uses_runtime_env_as_display_fallback`、`tests/test_system_config_service.py::test_get_config_runtime_env_fallback_does_not_persist_llm_fields_on_save`、`tests/test_system_config_service.py::test_runtime_env_fallback_does_not_override_saved_provider_and_base_url_settings`、以及 `tests/test_system_config_api.py` 的 `/api/v1/system/config` 獲取/儲存鏈路迴歸。
- [改進] Web 個股代號相關欄位（輸入框 placeholder、表格表頭、驗證錯誤訊息、告警標的標籤）統一將「股票程式碼」「標的程式碼」用語改為「股票代號」「標的代號」，原始碼語境的「程式碼」用語保留不變。
- [改進] Web 首頁、Settings 與 API 錯誤訊息中的「大盤覆盤」依語境拆分：首頁頂層操作與設定欄位統一改為「市場概覽」，報告/盤面回顧語境改為「盤勢回顧」；Settings `MARKET_REVIEW_REGION` 欄位標題改為「市場概覽範圍」，選項仍為台股/美股/全部市場。
- [改進] Web 持股頁「成本口徑」「顯示口徑」與區塊標題「口徑」分別改為「成本計算方式」「顯示維度」「帳戶與計價資訊」，移除中國證券術語慣用「口徑」一詞。
- [修復] zh_TW 本地化詞庫補上「震荡→震盪」映射，修正 LLM 自由文字敘述（如「震荡偏空」）經 Route B zh_TW 轉換後仍殘留簡體字的問題。
<!-- 新條目格式：- [型別] 描述（型別取值：新功能/改進/修復/文件/測試/chore）-->
<!-- 每條獨立一行追加到本段末尾，無需分類標題，合併時衝突最小 -->
- [新功能] 新增 fixture-first TaiwanFinMindFetcher 與台股 TW 2330/2454 離線行情、基本面、籌碼和公司資料 fixtures，供 TW+US Route B MVP Phase 2.1 驗證使用。
- [新功能] 新增 TW/US symbol normalizer，支援 TW:2330、2330.TW、US:AAPL 等顯式市場格式，並對無市場裸碼 fail fast。
- [新功能] 新增 TaiwanFinMindFetcher 四層網路守衛（DSA_FIXTURE_MODE / DSA_ALLOW_EXTERNAL_NETWORK / FINMIND_ENABLED / FINMIND_API_TOKEN），預設全離線；新增 US 市場 AAPL/NVDA 行情與新聞 fixtures；FinMind>=0.6.0 標記為可選依賴。
- [修復] 預設不再註冊 AlphaSift API 路由，需顯式啟用 `ALPHASIFT_ROUTE_ENABLED` 後才可暴露選股介面。
- [修復] 加固 server/WebUI/API 啟動安全門，預設僅允許本機監聽、忽略 wildcard CORS，並要求管理員認證與 PBKDF2 密碼雜湊就緒。
- [修復] SearXNG 預設關閉公共例項發現，fixture/no-network 模式禁止訪問 `searx.space`，僅保留顯式本機自建例項配置。
- [修復] 加固 server/WebUI 報告渲染路徑，避免 LLM/report/dashboard 內容中的指令碼、JavaScript URL 與事件處理器 payload 被瀏覽器執行。
- [文件] 補充 server-safe 本機 WebUI/API profile，明確需關閉 stock-index 遠端重新整理、公共搜尋發現、實時資料來源與通知路徑，並同步 SearXNG fail-closed 預設說明。
- [文件] 重大變更：`--serve` / `--serve-only` 現在強制要求 `ADMIN_AUTH_ENABLED=true` 並已儲存有效的 PBKDF2 管理員密碼雜湊方可啟動；未配置認證的現有本地部署將以 `ServerSafetyError` 拒絕啟動，需先透過 Web 設定流程或 `python -m src.auth reset_password` 完成初始化。
- [文件] 重大變更：YFinance/美股實時行情現在預設 fail-closed；在 `.env` 未顯式設定 `DSA_FIXTURE_MODE=false` 與 `DSA_ALLOW_EXTERNAL_NETWORK=true` 時，有 fixture 的股票靜默使用離線 fixture 資料，無 fixture 的股票將以 `DataFetchError` 拒絕請求，這是 Route B 離線優先的刻意安全邊界。
- [文件] MVP 範圍說明：TaiwanFinMindFetcher 的 chips/fundamentals/company_profile 方法為 fixture-only 路徑，不受四層網路守衛控制；Phase 3.3 live smoke 僅覆蓋 daily bars，補充資料實時化延至後續 Phase。
- [修復] US 股票程式碼正則擴充套件支援多類別程式碼（BRK.B、BRK-B、BF.B 等），新增 `([.-][A-Z]{1,2})?` 可選字尾。
- [新功能] Route B 新增 TW/US runtime scope gate（`ROUTE_B_ENFORCE_MARKET_SCOPE`）：A 股 / CN 股票程式碼被拒絕，空 TW/US watchlist fail-closed 並附可操作錯誤提示；CN-only 資料來源（Efinance/Akshare/Baostock/Pytdx）不會被呼叫。
- [新功能] 新增大盤復盤多市場設定 `MARKET_REVIEW_REGIONS=TW,US`；Route B 模式下大盤復盤預設啟用 TW+US，CN/A 股大盤復盤被封鎖（附 warning 日誌），TW 大盤復盤標記為 deferred（尚未實作），US 大盤復盤正常啟用。
- [改進] Config 新增 `route_b_enforce_market_scope`、`route_b_markets`、`market_review_regions` 欄位，對應環境變數 `ROUTE_B_ENFORCE_MARKET_SCOPE`、`ROUTE_B_MARKETS`、`MARKET_REVIEW_REGIONS`。
- [修復] `_analyze_with_prebuilt` 現在將 `query_id` 寫入返回結果，與常規分析路徑行為對齊。
- [修復] fixture/no-network 模式下股票名稱現在從 `tests/fixtures/market/<market>/<symbol>/company_profile.json` 的 `name` 欄位讀取，不再回退到原始程式碼符號（如 `TW:2330`、`US:AAPL`）。
- [修復] `DSA_ALLOW_EXTERNAL_NETWORK` 空值或未設定時現在正確視為禁用（fail-closed），僅 `1/true/yes/on` 等顯式允許值才開放外網；原錯誤邏輯導致空字串被誤判為允許外網。
- [修復] 釋出說明生成查詢 PR 作者失敗時保留降級並輸出包含 PR 編號和異常型別的 warning，便於排查 token、許可權、網路或 GitHub API 異常。
- [修復] 修正 `VALID_MARKETS` 缺少 `tw`，導致台股持股帳戶建立時回傳 400 錯誤。
- [修復] 修正 `_default_currency_for_market("tw")` 回傳 CNY 的問題，台股交易未指定幣種時現正確預設為 TWD；未知市場的兜底值由 CNY 改為 TWD，既有 CN 市場資料維持 CNY 不變。
- [修復] 修正持股組合彙總幣種 `aggregate_currency` 硬編碼 CNY 的問題，現依帳戶基準幣種或預設 TWD 顯示，不再於空帳戶或台股/美股帳戶情境下誤顯示 CNY。
- [修復] 持股帳戶與每日快照資料庫欄位預設值由 `cn`/`CNY` 改為 `tw`/`TWD`，與既有 Pydantic schema 預設值對齊。
- [改進] Web 持股頁面新建帳戶市場下拉選單移除 A 股 / 港股選項，僅保留台股、美股。
- [改進] 根 README 改為繁體中文 TW/US-only 首頁，移除簡體中文入口、贊助商、聯絡合作與非台股/美股範例。
- [改進] AlphaSift 篩選請求的 `market` 欄位移除隱式 `cn` 預設值，改為必填欄位；AlphaSift 維持預設停用，不影響主流程。

## [3.22.0] - 2026-06-13

### 釋出亮點

- feat: 新增 DecisionSignal 獨立儲存與 API、執行流快照 API 和 Web 執行流檢視，補齊建議動作結構化欄位與歷史/回測展示鏈路。
- feat: AlphaSift 熱點題材鏈路升級為新版合約，支援熱點榜單、題材詳情、發酵路線、概念股詳情、快取與兜底資料來源。
- feat: 個股分析預設注入當日大盤環境摘要，並在高風險/退潮環境下軟化激進買進建議。
- fix: 修復問股歷史追問標的上下文、自選股等價程式碼匹配、低質量新聞過濾、執行流脫敏與 AlphaSift 熱點詳情展示等穩定性問題。

### 新功能

- 新增獨立 `DecisionSignal` 儲存、Repository、Service 與 `/api/v1/decision-signals` API，支援來源/市場/股票/動作/期限/階段去重、查詢、續期、狀態更新、懶過期、持股過濾和敏感資訊脫敏。
- 新增分析任務與歷史報告執行流快照 API，提供 lanes、nodes、edges、events、summary 等統一契約，並從任務佇列、執行診斷和 AnalysisContextPack overview 構建脫敏資料流/資訊流。
- Web 端為活躍任務、歷史報告和大盤覆盤報告補充執行流檢視入口，支援檢視執行摘要、拓撲節點、事件流和基礎排障詳情。
- 新增 AlphaSift 熱點題材鏈路：後端提供 `/api/v1/alphasift/hotspots` 與 `/api/v1/alphasift/hotspots/{topic}` API，Web 選股頁新增熱點題材區域並支援發酵路線與概念股檢視。

### 改進

- 個股分析新增按當日/市場複用的大盤環境摘要，普通 Pipeline 與 Agent 分析 Prompt 可讀取低敏大盤背景；新增預設開啟的 `DAILY_MARKET_CONTEXT_ENABLED` 配置，使用者仍可顯式關閉。
- 個股分析與歷史/回測展示新增可選八態 `action` / `action_label` 建議動作欄位，保留 `operation_advice` 自由文字和 `decision_type=buy|hold|sell` 統計口徑。
- 補充 Web decision-signals typed API wrapper 與契約隔離測試，暫不接入 UI。
- 完善執行時日誌上下文，補充 logger name、觸發來源、市場統計與實時行情預取鏈路狀態，便於排查排程、API、Bot 和資料來源降級路徑。
- 持股管理頁新增持股帳戶刪除入口，複用現有帳戶軟刪除介面，誤建帳戶會從預設列表、快照、風險、錄入入口和事件列表隱藏且不物理清理歷史流水。
- AlphaSift 依賴鎖定更新到 `d038c52c468543726fc1fd830b53c27d3f09d6da`，併為新版 last-good snapshot、日線歷史、行業/概念 provider cache、hotspot 榜單、題材發酵路線、概念股詳情、上次成功熱點快取與 post-analysis 元資訊補齊 DSA 執行期和 Web 適配。
- AlphaSift 熱點題材讀取預設優先使用上次成功快取，手動重新整理才實時拉取並覆蓋快取，實時拉取失敗時儘量回退舊快取。
- AlphaSift 熱點題材區域改為預設摺疊，展開並選中具體題材後再讀取詳情；發酵路線改為帶時間標記的時間線展示，概念股可點選進入首頁並直接啟動分析。
- AlphaSift 熱點題材資料鏈路複用同一次東方財富板塊異動快照，並從真實漲跌幅、異動次數和高頻個股推導趨勢分、持續分、階段與龍頭樣本。
- AlphaSift 熱點題材重新整理在合約層返回少量或缺少關鍵欄位時改用 DSA 東方財富板塊異動直連榜單，忽略少於 3 條的本地熱點快取，並補齊板塊兜底欄位。
- AlphaSift 熱點題材卡片改為更緊湊的多列布局，概念股列表改為獨立“分析”按鈕觸發個股分析；詳情優先合併東方財富成分股、同花順解析和板塊異動龍頭兜底並按日聚合發酵時間線。
- AlphaSift 熱點題材詳情新增 DSA 側 30 分鐘磁碟快取，重複點開同一題材時複用發酵時間線與概念股詳情；題材事件僅展示 AlphaSift 合約時間線、同花順摘要、已配置新聞搜尋或東財板塊異動等真實來源。
- AlphaSift 熱點題材訊息催化改為摘要展示：配置 LLM 時優先壓縮為一句題材催化摘要，未配置或呼叫失敗時回退本地短摘要。
- AlphaSift 熱點題材列表新增可選 `include_details` 詳情預取，Web 預設隨熱點列表批次帶回 Top 題材發酵路線與概念股並複用前端記憶體快取；新聞催化在 LLM 不可用時改為本地事件歸納。
- 改造 `main.py --webui-only` 啟動行為：若 FastAPI 監聽埠已被佔用，啟動即 fail-fast 丟擲明確錯誤並退出。

### 修復

- 問股從歷史報告進入後的追問會持續攜帶當前標的，切回或過載已有會話時可從歷史訊息恢復基礎當前標的，並由後端阻斷未明確切換時的錯誤股票工具呼叫、交易所片段和指標縮寫誤路由。
- 自選股加入和刪除按等價股票程式碼匹配港股及大小寫美股變體，避免 `00700`、`HK00700`、`00700.HK` 或 `aapl`、`AAPL` 被誤判為不同標的。
- 收緊建議動作 legacy fallback：否定/迴避表達、中文金融上下文、`buy or sell`、多 guard 歧義文字以及英文複合詞不再誤渲染成 action badge；有結構化 `action` 時回測/歷史趨勢等入口按介面語言顯示 action 標籤。
- 股票新聞與多維情報搜尋在相關度排序後新增域名無關的准入過濾，剔除下載/安裝包/應用評分頁及成人/招嫖服務垃圾頁，並在同批已有有效標的/行業候選時移除 `score=0` 背景填充項。
- 修復歷史報告執行流快照在混合時區事件時間戳下返回 500 的問題。
- 修復執行流 live SSE 事件未複用快照層遞迴脫敏規則的問題，避免本地路徑、prompt/raw response、代理頭等敏感診斷欄位在 refetch 前短暫暴露。
- AlphaSift 熱點題材預設載入在無快取且舊適配層缺少 `alphasift.hotspot` 模組時返回空態，不再一開啟選股頁就顯示 AlphaSift 未就緒；手動重新整理仍會提示依賴需更新。
- 為 THS 發酵路線補充列名兜底：當 `stock_board_concept_summary_ths` 返回缺列時僅跳過該來源富化，不影響熱點題材詳情 API 返回。
- 桌面釋出打包改用凍結可執行檔案執行時探針校驗 `alphasift.dsa_adapter`，避免 macOS PyInstaller 將模組內嵌進可執行檔案時被檔案系統/zip 掃描誤判為缺失。
- AlphaSift 熱點題材詳情展示改為優先使用後端融合後的 `route`，避免舊 `timeline` 覆蓋新聞/LLM 摘要；手動重新整理熱點榜單時會同步繞過同題材詳情快取。

### 文件

- README 與繁中 README 快速開始入口補充影片教程連結，並將桌面客戶端入口文案調整為客戶端配置教程。
- 補充 `docs/alphasift-integration.md`：明確 AlphaSift 鎖定 commit 來源、Hotspot 契約邊界、LLM/LiteLLM 相容語義與關閉開關下回退路徑。
- 補充 #1381 執行時範圍、相容邊界、官方語義依據與常規釋出回滾說明。

### 測試

- 覆蓋 #1381 後端 runtime 與相容核驗：`tests/test_main_schedule_mode.py`、`tests/test_pipeline_daily_market_context.py`、`tests/test_daily_market_context.py`、`tests/test_daily_market_context_guardrail.py`、`tests/test_agent_executor.py`、`tests/test_config_env_compat.py`、`tests/test_config_registry.py` 與 `apps/dsa-web/tests/system_config_i18n.test.ts`。
- 新增/更新 AlphaSift 後端迴歸：`python -m pytest tests/test_alphasift_api.py -q`、`python -m pytest tests/test_docker_entrypoint.py -q`、`python -m pytest tests/test_main_schedule_mode.py -q -k "start_api_server_fails_before_thread_when_port_is_busy"`。

## [3.21.0] - 2026-06-07

### 釋出亮點

- feat: 新增 Web UI 中英文介面語言切換和飛書 App Bot 通知模式，提升多人部署和企業通知場景體驗。
- feat: 大盤覆盤報告、歷史入口和個股欄繼續收口到結構化資料與統一 Markdown/GFM 渲染，Web/API 人工觸發入口不再被交易日 gate 短路。
- feat: AlphaSift 選股鏈路改為可恢復後臺任務，並完善 DSA LLM runtime bridge、預設適配層預置和相容迴歸。
- fix: 修復英文介面殘留中文、診斷展示、執行時環境變數展示、健康檢查、桌面更新路徑、工作流變數讀取和多處 Web 窄佈局問題。

### 新功能

- WebUI 新增獨立介面語言狀態與中英文切換入口，覆蓋主導航、首頁、登入、設定頁和通用控制元件文案；UI 語言與 `report_language` 解耦，不改寫報告語言鏈路。
- 飛書通知新增應用機器人（App Bot）模式，支援透過 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_CHAT_ID` 配置，無需額外建立自定義機器人。
- Web 大盤覆盤報告新增專用展示檢視，歷史入口和首頁即時結果統一使用 Markdown/GFM 渲染並隱藏個股專屬模組。
- 大盤覆盤新增結構化 `market_review_payload`，Web、歷史詳情和推送統一基於結構化資料渲染，並保留 Markdown 相容展示。
- 新增預設關閉的 AlphaSift 選股頁籤，透過 `ALPHASIFT_ENABLED` 明確控制，並保留 `/install` 作為顯式修復路徑。

### 改進

- Web/API 大盤覆盤人工觸發入口不再因交易日檢查或相關市場休市而短路跳過；定時任務、GitHub Actions 手動執行和 CLI 預設入口仍保持原交易日 gate。
- AlphaSift Web 選股改為後臺任務提交與狀態輪詢，新增可恢復任務狀態展示，避免外部快照、行情或 LLM 變慢時瀏覽器長請求超時。
- AlphaSift 選股 API 與服務層收斂到 `AlphaSiftService`，endpoint 僅做路由引數接收與錯誤對映。
- AlphaSift 與 DSA 的執行時 LLM 相容橋接改為呼叫期注入，保留 `provider/model/base_url/custom headers/fallback` 語義鏈路，不做持久化遷移。
- Web 首頁側欄不再單獨展示大盤覆盤歷史集合，最新大盤覆盤作為 `MARKET` 併入個股欄，按最近分析時間參與排序，並複用個股欄的選擇、刪除、完整報告與歷史趨勢檢視能力。
- 多股通知報告將市場階段收斂為總覽下方單行 `市場狀態`，不再在每隻股票摘要下重複展示資料質量和限制詳情。
- API 錯誤響應構造收斂到共享 helper，保持既有錯誤 envelope 形狀並降低 endpoint 重複程式碼。
- WebUI 繫結公網地址或 CORS 全開放且未啟用管理員認證時新增執行時 warning；僅增加可觀測性，不阻斷啟動、不改寫配置。
- 資料庫初始化新增 `schema_migrations` baseline 標記表與冪等記錄，用於後續 schema 演進追蹤；不遷移、不清理、不改寫既有業務表資料。
- #1386 P6 複用市場階段與 AnalysisContextPack 公開摘要聯動警告、持股手動分析、歷史、回測和通知展示，不新增資料庫遷移。

### 修復

- Web 英文介面補齊回測、組合風險與警告規則相關文案本地化，避免英文模式下殘留中文篩選器、按鈕和列舉標籤。
- 綜合情報搜尋中的機構分析與業績預期維度改用 180 天 provider 請求視窗，避免預設短新聞視窗漏掉財報、研報等週期性財經材料。
- Web 個股欄和歷史卡片在窄佈局下不再讓市場階段標籤遮擋股票名稱。
- 問股自由文字追問不再將 TTM、PE、YOY 等金融縮寫誤識別為新股票程式碼。
- [修復] GitHub Actions 每日分析工作流讀取 SearXNG 自建例項地址時支援 Variables 優先、Secrets 回退，修復僅配置 Variables 時 URL 不生效的問題。
- Web/桌面端左側導航選中態改用 border 實現，避免藍色豎條指示器溢位側欄邊界；側欄展開寬度 116px -> 136px，新增 rail 緊湊模式。
- Windows 桌面端自動更新安裝目錄不再預先加引號，避免帶空格路徑在自動安裝時觸發“缺少快捷方式 / 找不到 Daily Stock Analysis.exe”的系統彈窗。
- Agent 分析路徑生成 AnalysisContextPack overview 前複用已落庫日線分析上下文，避免日線已抓取成功仍顯示 `daily_bars_missing`。
- 修正大盤覆盤結構化 `breadth` 的可用性判斷：當市場不支援或抓取失敗時不下發 `breadth`，前端展示“暫無資料”，避免誤導性 0 值。
- 大盤覆盤語言行為遵循全域性 `report_language`，並在美股中文場景下本地化市場標籤與策略藍圖，避免混入英文策略段落。
- Docker Web 設定頁讀取配置時在活躍 `.env` 檔案缺項時回退展示啟動注入的同名環境變數，並補清相關掛載邊界文件。
- 報告頁執行診斷會區分資料來源抓取成功與進入 LLM 分析輸入，相關新聞區標註為報告頁補充/後續檢索資訊，避免與輸入資料塊狀態互相誤讀。
- `/health` 根路徑健康檢查現在始終返回 JSON，避免靜態 Web fallback 吞掉健康探針；`/api/health` 與 `/api/v1/health` 繼續保持相容。
- `ALPHASIFT_ENABLED` 關閉時不觸發 `alphasift` 執行時注入；開啟後優先複用已配置的 DSA/provider 配置並注入 `LITELLM_*` 與 `LLM_*` 執行時變數。
- 補齊 openai-compatible 場景下 base URL、`extra_headers` 與 `LITELLM_FALLBACK_MODELS` 的相容路徑與回退鏈驗證。
- 桌面/映象打包鏈路保持與執行時一致的 AlphaSift 適配層預置，避免 `pip install` 作為線上修復依賴。

### 文件

- 明確 Issue #777 UI 語言切換採用倉內 `UiLanguageContext` + `uiText` 實現，持久化 key 為 `dsa.uiLanguage`，並補充對應視覺化驗收指引。
- 明確大盤覆盤展示鏈路、結構化 payload、語言行為、交易日 gate 差異和回滾邊界。
- 補充 LLM / LiteLLM 相容鍵在 Settings 展示與校驗上下文中的回退邊界，說明不改寫、不遷移、不清理使用者現有 provider/model/base URL 持久化配置。
- 補齊 #1602 執行診斷口徑修復覆蓋範圍，說明僅統一輸入與展示口徑，回滾方式為常規釋出回滾。
- 明確 AnalysisContextPack P6 文件、遷移與回滾邊界，並同步既有 `SAVE_CONTEXT_SNAPSHOT` 到 `.env.example`、配置登錄檔、Web 設定幫助和完整指南。
- 補齊 #1386 P7 盤前/盤中/盤後分析的入口、遷移、回滾和使用者可見說明。
- 為 AlphaSift runtime bridge 增加官方相容依據落點，明確 provider/model/base_url/extra_headers/fallback 與回退邊界。

### 測試

- Web 方向執行 `npm run lint`、`npm run build`、相關 Vitest 和 smoke 命令；未設定 `DSA_WEB_SMOKE_PASSWORD` 時 smoke 用例按設計 skip。
- Web 測試執行時宣告 Node `>=20.19.0 <27` 與 npm `>=10`，並補 localStorage 測試兜底以穩定 Vitest。
- 增補 AlphaSift runtime bridge 與打包指令碼靜態驗證，覆蓋 `LLM_CHANNELS`、`LITELLM_FALLBACK_MODELS`、`alphasift.dsa_adapter`、`--collect-all alphasift`。

### chore

- 移除隨 issue / PR 驗收流程誤入庫的截圖資產，並明確一次性截圖證據應保留在 PR 描述、評論、附件或 artifact 中，不作為倉庫檔案合入。

## [3.20.0] - 2026-06-03

### 釋出亮點

- feat: 新增 AlphaSift 選股入口、自動安裝與穩定適配層，支援 Web 策略執行、LLM 重排展示和預設關閉的可控啟用。
- feat: 完善個股歷史、自選佇列、市場階段與 AnalysisContextPack 可見性，增強 Web 報告和 API 的結構化上下文能力。
- feat: MiniMax 預設模型升級到 `MiniMax-M3`，並補齊相關價格、預設和測試覆蓋。
- fix: 修復健康檢查、Windows 桌面更新與首次執行編碼、ETF 日線 secid、LLM base_url 校驗和 Agent 日線上下文誤判等穩定性問題。

### 新功能

- 新增預設關閉的 AlphaSift 選股頁籤，透過 `ALPHASIFT_ENABLED` 開啟後經由穩定適配層讀取策略並執行選股。
- Web 首頁左側欄改為個股欄，按股票去重展示，大盤覆盤置頂，點選個股載入最新報告，支援按程式碼變體（.SZ/.SH/.SS）歸一化去重合並。保留全選、批次刪除和刪除確認入口；新增按股票程式碼批次刪除 API `DELETE /api/v1/history/by-code/{stock_code}`。
- 報告詳情右側欄新增自選操作入口，支援檢視當前股票是否在自選佇列、一鍵加入或移除；大盤覆盤報告不顯示該操作。
- 問股頁面輸入區上方新增自選操作按鈕，使用者傳送包含股票程式碼的訊息後自動顯示加入自選/從自選刪除入口。
- Web 報告頁新增同股歷史趨勢抽屜入口，歷史列表摘要補充趨勢、摘要、模型和分析時行情欄位，支援按當前股票檢視歷史分析並載入更多。
- AnalysisContextPack P4 低敏 overview 接入歷史詳情、同步分析響應、completed 任務狀態和 Web 報告頁，展示資料塊狀態、來源、缺失原因與降級摘要。
- #1386 P5 為個股分析報告新增 `dashboard.phase_decision` 盤中決策護欄，並在儲存歷史前按市場階段與資料質量限制高置信盤中買賣結論。
- #1386 P4a 新增 `analysis_phase=auto|premarket|intraday|postmarket` API 引數，並在非同步任務 accepted、記憶體 status、list、SSE 與分析 pipeline 中透傳請求階段。
- #1386 P4b Web 報告頁新增最終市場階段標籤，任務面板展示請求階段，並複用 AnalysisContextPack 低敏資料質量摘要。
- MiniMax 通道模型列表升級：新增 `MiniMax-M3` 並作為預設，按官方 OpenAI-compatible 文件支援 1M 輸入上下文（專案保守註冊為 `<=512K` 價格檔：context_window 512K、`max_tokens` 128K，對應 $0.6/M 輸入、$2.4/M 輸出，>512K 輸入價格檔未建模），保留 `MiniMax-M2.7` 與 `MiniMax-M2.7-highspeed`，並保留 `MiniMax-M2.5` legacy 價格條目以相容現有使用者配置的成本估算。Web 設定頁 MiniMax 預設模型與價格按 M3 重新整理。
- 新增 AnalysisContextPack P1 內部契約與脫敏序列化測試。
- 市場階段低敏摘要接入歷史詳情、同步分析響應和 completed 任務狀態的 report metadata。

### 改進

- 首次執行配置校驗補充缺失 AI Key、空 STOCK_LIST、Telegram/郵件成對欄位和 Webhook URL 字首診斷。
- AlphaSift 選股入口在 Web 側邊欄中移動到“問股”下方，貼近 Agent/研究輔助工作流。
- Docker 映象構建階段預置預設 AlphaSift 適配層，與桌面釋出包一樣避免執行期額外安裝。
- AlphaSift 選股改為依賴 `alphasift.dsa_adapter` 的穩定介面，Web 策略列表由 AlphaSift 動態提供，不再在前端硬編碼。
- AlphaSift 選股頁補充 Run ID、快照數、過濾後數量、因子和風險詳情，展開候選時展示真實明細，並暫時僅開放當前支援的 A 股市場。
- Web 設定頁新增 AlphaSift 選股開關卡片，可直接開啟或關閉選股頁籤。
- 開啟 AlphaSift 選股時先切換 `ALPHASIFT_ENABLED` 並檢查適配層可用性，缺失時自動呼叫受控安裝介面，不再要求使用者額外點選安裝。
- AlphaSift 已開啟但適配層缺失時，策略列表和選股介面會序列化自動安裝鎖定來源，並強制重灌以覆蓋舊版 `alphasift` 包。
- AlphaSift 選股頁合併重複的快照源 fallback 提示，並保留 AlphaSift 自身的 Tushare 優先快照源邏輯。
- AlphaSift 選股頁在 LLM 重排降級時展示 warning/source error/parse error，並避免把本地因子評分誤顯示為 LLM 判斷。
- Web 設定頁不再把 `ALPHASIFT_ENABLED` 作為普通資料來源配置項重複展示，該值僅作為“開啟選股”按鈕背後的持久化狀態。
- AlphaSift 關閉時隱藏 Web 左側“選股”導航入口，避免誤導未開啟使用者。
- 補充 AlphaSift 選股自定義策略顯示邏輯，避免未匹配預設項時誤顯示“均衡多因子”。
- 新增 GET /api/v1/history/stocks 端點按 code 分組返回不重複個股列表；新增 GET /api/v1/stocks/watchlist、POST /api/v1/stocks/watchlist/add、POST /api/v1/stocks/watchlist/remove 端點支援自選佇列增刪查。STOCK_LIST 讀寫保持原樣，不做自動歸一化；add/remove 時歸一化比較判斷等價程式碼變體。
- 新增 useWatchlist hook 統一管理自選佇列前端狀態，複用 SystemConfigService 的 STOCK_LIST 配置項實現持久化。
- AnalysisContextPack P5 增加資料質量評分、`fetch_failed` 狀態、Prompt 資料限制區塊和 Web 低敏質量展示。
- #1386 P2-full 在 AnalysisContextPack Prompt 資料限制中追加市場階段與降級資料的交叉約束，並修正中文分析 Prompt 的階段化行情標籤。
- 通知報告預設傳送路徑恢復既有通道相容轉換與分片邏輯，新增 renderer 能力僅保留為未來擴充套件基礎。
- 關聯板塊缺少型別資料時改為單行展示板塊名稱，避免生成整列 `N/A` 的板塊表格。
- 最佳化 Web 報告詳情頁資訊層級，將輸入資料塊和執行診斷下移為主體內容後的摺疊輔助資訊。
- 盤中分析補齊實時行情獲取時間、provider 時間、stale、fallback 與 partial/estimated 標記，供 AnalysisContextPack 對映輸入資料限制。

### 修復

- Agent 分析路徑生成 AnalysisContextPack overview 前複用已落庫日線分析上下文，避免日線已抓取成功仍顯示 `daily_bars_missing`。
- 註冊 /api/v1/health 路由並加入認證豁免，修復該路徑返回 404 以及開啟 ADMIN_AUTH_ENABLED 後健康探針收到 401 的問題。
- Windows 本地首次執行環境檢查相容非 UTF-8 控制檯輸出，並將 `requirements.txt` 註釋改為 ASCII 以降低預設內碼表下的依賴安裝失敗機率。
- AlphaSift DSA 適配層預設開啟 LLM 重排，後端顯式請求 `use_llm=True`，選股頁展示 LLM 分數、判斷、覆蓋率和關注項。
- AlphaSift 嵌入 DSA 時複用 DSA 已解析的 LLM 模型、通道和金鑰配置，避免 Web 已配置 LLM 但選股 LLM 重排仍因缺少 provider key 降級。
- AlphaSift 選股複用 DSA LLM 路由時過濾未宣告的託管 provider 備選模型，並把已宣告通道模型補入回退鏈，避免殘留 Gemini fallback 覆蓋可用的 DSA 通道。
- AlphaSift 預設安裝來源改為鎖定 commit 的受信任 GitHub 地址；桌面模式自動安裝不要求管理員會話，非桌面部署要求管理員認證會話，並繼續限制安裝來源。
- 修復 Web 開啟 AlphaSift 時先安裝後寫配置導致預設關閉狀態無法開啟的問題。
- AlphaSift 狀態與安裝介面不再返回 `install_spec` 明文，僅返回 `install_spec_is_default` 等非敏感狀態欄位。
- AlphaSift 狀態探測區分可選依賴缺失與非預期異常，異常場景記錄 warning 並返回非敏感診斷資訊。
- 調整 AlphaSift 篩選呼叫相容：`screen` 以 `max_results` 為主並支援歷史 `max_output` 關鍵詞，同時允許策略透傳以對齊前端手動策略引數。
- AlphaSift Web 選股請求使用獨立長超時，避免開啟 LLM 重排後被通用 30 秒 API 超時提前中斷。
- 桌面端打包階段預置 AlphaSift 並收集適配層，避免釋出包執行時再要求管理員自動安裝。
- AlphaSift 自動安裝僅在 `status` 診斷為 `missing_module` 時觸發（僅模組缺失場景）；適配層可匯入但執行時異常不再自動 `pip install`，而是返回 `424` 並保留診斷，避免把真實執行時故障掩蓋為重灌。
- 收口 Web 中文介面殘留英文文案與設定頁 help 缺口，回測頁改為中文展示，並讓 Web 設定頁僅展示已註冊且帶說明的配置項。
- Windows 桌面端自動更新靜默安裝時顯式複用當前安裝目錄，避免自定義安裝目錄場景下解除安裝舊版本檔案失敗。
- Windows 安裝器重試舊解除安裝器時對 `_?=` 安裝目錄引數加引號，修復舊版本安裝在帶空格路徑時返回 2 導致自動更新失敗。
- Windows 桌面端自動更新傳給 NSIS 的 `/D=` 目錄引數在包含空格時自動加引號，避免安裝位置登錄檔被截斷。
- 加固 LLM channel base_url 校驗，避免解析差異導致 SSRF 繞過。
- 修正 efinance ETF 日線 Eastmoney secid 路由，避免滬市 ETF 被按深市 quote id 查詢導致日線為空。

### 文件

- 明確 AlphaSift 與 LiteLLM 相容邊界：僅橋接 DSA 已宣告 provider/model/base URL 為呼叫期注入，不對 `.env` 做 provider/model 路由遷移；回退方式為關閉 AlphaSift 並恢復原有 `LITELLM_*`/`LLM_*` 配置。
- 明確 AlphaSift 僅複用 DSA 現有 LLM/LiteLLM 配置語義，不新增 `LITELLM_MODEL`、`OPENAI_MODEL`、`OPENAI_BASE_URL`、`LLM_TIMEOUT_SEC` 等模型語義遷移；失敗提示與回退路徑統一沿用既有系統配置鏈路，僅影響 AlphaSift 選股能力本身。
- 明確 AlphaSift 自動安裝來源鎖定、`missing_module` 與執行時異常行為邊界，以及 LLM/provider/base URL 與自定義通道回退路徑，便於問題溯源與回滾到原有 LLM 配置。
- 明確同股歷史趨勢新增模型欄位為歷史快照展示後設資料，不影響執行時 LLM Provider/Model/Base URL 路由與配置遷移清理；回退方式為按常規釋出回滾本變更。
- 明確 #1311 的相容性邊界：渲染層僅消費分析結果 `model_used` 展示欄位，未改動 `wechat/slack/feishu/telegram` sender 傳送鏈路，不觸發 provider/model/base_url 相容遷移。
- 明確 AlphaSift 鎖定 commit 的 `alphasift.dsa_adapter` 契約依據，以及當前 DSA API/Web 呼叫結構的相容邊界。
- 明確 Settings 頁面對 LLM 配置僅做展示分組與欄位歸併，不改寫或觸發 LLM 遷移/回退路徑；相容現有 `LLM` 配置儲存與回退語義。
- 新增 AnalysisContextPack P0 上下文盤點。
- 補齊警告中心 P8 文件與配置收口說明，明確 legacy JSON、高階規則、Web/API、Docker、GitHub Actions 與 Desktop 邊界。

### 測試

- 同步更新 `llmProviderTemplates`、LiteLLM fallback pricing 與 MiniMax 預設相關單測，斷言新預設模型。
- 補充 ETF 日線資料來源路由、輸入變體、fallback 與 MA 欄位迴歸覆蓋。

### chore

- 新增通知報告通道能力畫像、PreparedMessage 與結構感知 Markdown 分片基礎設施，為 #1311 全通道渲染適配打底。
- 預置企業微信、飛書、Telegram、釘釘、Slack 平臺 renderer 後設資料，暫不改變預設推送報告入口和可見版式。

## [3.19.0] - 2026-05-29

### 新功能

- 落地 #1391 Phase 1 執行診斷最小鏈路：任務/SSE 追加 trace_id，並記錄日線與實時行情 ProviderRun 快照。
- 警告中心新增 P7 大盤紅綠燈結構化規則，支援 `market_light_status` 與 `market_light_score_drop` 並複用現有 worker、觸發歷史、通知和冷卻鏈路。
- 落地 #1391 Phase 2 執行診斷摘要：生成使用者可讀 RunDiagnosticSummary，提供歷史報告診斷 API 與脫敏複製文字。
- 落地 #1391 Phase 3 執行診斷可見性：報告詳情和任務面板預設摺疊展示執行狀態、trace 與可複製排障資訊；後端透過 `api/v1/history/{record_id}/diagnostics` 與 `context_snapshot.diagnostics` 提供歷史鏈路回填。
- 新增 AnalysisContextPack P1 內部契約與脫敏序列化測試。
- 新增 AnalysisContextPack P2 builder，從普通分析 pipeline 已有 artifacts 組裝內部上下文包。
- 問股新增預設關閉的可見對話上下文壓縮，支援 Web 開關、Agent 高階 preset、滾動摘要和最近輪次原文保護，降低長會話 token 消耗。
- 股票自動補全索引預設支援從 GitHub main 遠端重新整理並快取到本地，Web/CLI 分析入口失敗時自動降級到內建索引，降低摘帽和更名後舊簡稱汙染分析的機率。
- 普通分析與 Agent 執行時 Prompt 接入 AnalysisContextPack 低敏摘要，保持 history/API/Web 輸出相容。

### 改進

- `scripts/fetch_tushare_stock_list.py` 可對 A 股中帶 `XD`/`XR`/`DR`/`N`/`C` 字首的名稱進行回填修正，供自動補全重新整理流程預設使用。
- Web 路由頁面改為按需載入，降低首包體積並增加路由載入失敗恢復提示。
- Web 完整報告 Markdown 抽屜改為按需載入。
- 新增市場階段推斷基線並明確盤前、盤中、午休、臨近收盤、盤後和非交易日語義。
- 新增執行態市場階段上下文構造與降級測試。
- 設定頁配置幫助階段性補齊 Web 設定頁實際展示/可配置欄位的中英雙語文案，覆蓋 Agent、回測、報告、通知路由、系統執行時、AI legacy、資料來源和通知高階配置。
- P2-min：LLM Prompt 注入市場階段上下文。

### 修復

- 股票自動補全索引生成缺少 `pypinyin` 時改為直接失敗，避免寫出缺失拼音欄位的降級索引。
- 歸一騰訊實時行情成交量為股口徑，避免量能變化倍數被放大並誤導分析報告。
- Docker 預設部署移除 `.env` 單檔案掛載，避免 WebUI 儲存配置時因 `os.replace` 更新掛載點觸發 `Device or resource busy`。
- 收斂 #1391 Phase 0 A 股程式碼歸屬邊界：補齊 `SH`/`SZ` 字首場景的歸屬一致性，明確 `data_provider/baostock_fetcher.py`、`data_provider/pytdx_fetcher.py`、`data_provider/tushare_fetcher.py` 的本輪修復範圍。
- 修復 `STOCK_LIST` 使用裸 A 股程式碼時 Baostock 等資料來源 fallback 的內部格式轉換，保持使用者配置繼續使用 6 位股票編號。
- Windows 桌面端自動更新在使用者確認重啟安裝後改為靜默執行安裝器，並在停止內建後端後清理程序引用，降低安裝器提示“每日股票分析無法關閉”的機率。
- macOS 桌面端將執行時配置遷移到使用者資料目錄，並在舊 `.app` 包內檔案仍可訪問時遷移 `.env`、資料庫和日誌，避免後續替換升級後重新配置。
- 恢復 Agent/歷史相容快照中的關聯板塊與板塊聯動欄位提取，修復新版首頁報告缺少“板塊聯動”的迴歸問題。
- 修正 Web 設定幫助中 legacy 警告 JSON 欄位名與靜默時段投遞語義說明。
- 修復 Web 中文設定頁在資料來源、通知、系統與 Agent 區域的配置標題、說明和關鍵下拉選項漏翻問題。
- 修復問股會話切換和首頁任務重連後可能殘留 Agent/分析任務進行中狀態的問題。
- 問股 single-agent 新增 provider-aware trace 分軌，跨輪保留 DeepSeek V4 thinking + tool-call 的 `reasoning_content` 與工具協議材料。
- 為 Akshare 新浪/騰訊 A 股歷史兜底介面增加呼叫級超時，並補齊 Tushare `605xxx` 滬市程式碼路由迴歸測試，避免定時分析因資料來源無響應而掛起。
- 將 `exchange-calendars` 依賴下限提升到 `4.13.0`，避免 pandas 3 環境匯入交易日曆時因 Timedelta 單位 `T` 失效導致分析失敗。
- 互動式命令（釘釘會話、飛書會話、Telegram）觸發的分析結果只回到來源會話，不再同時廣播到靜態通知通道。
- 適配 Longbridge OAuth 2.0 認證與 token 快取恢復，避免新後臺無 Legacy Access Token 時長橋資料來源被誤判為未配置。
- Longbridge OAuth 路徑在當前 SDK 不支援 `OAuthBuilder` / `Config.from_oauth` 時明確日誌降級，避免 Linux/Docker 僅可安裝舊 SDK 時構建失敗。
- 相容 YFinance 日線返回未命名日期索引的場景，避免標準化後缺少 `date` 列導致美股日線 fallback 中斷。

### 文件

- 新增 #1391 Phase 0 執行診斷契約文件，明確 trace_id、診斷摘要、關鍵鏈路範圍與脫敏/fail-open/retention 邊界。
- 補齊警告中心 P8 文件與配置收口說明，明確 legacy JSON、高階規則、Web/API、Docker、GitHub Actions 與 Desktop 邊界。
- 說明本次桌面修復僅覆蓋 Windows NSIS 更新安裝鏈路與後端程序生命週期清理；未改動設定項儲存/模型執行時清理語義。移除此前誤入的 `docker/Dockerfile` `npm registry` 變更，恢復部署構建與更新修復的職責隔離。
- 新增 AnalysisContextPack P0 上下文盤點，明確欄位質量狀態、現有狀態對映和首版 pack 邊界。
- 明確 #1391 Phase 2 的結構化檢測警告為非配置遷移訊號：`agent_max_steps`/`agent_orchestrator_timeout_s` 非法值會 fallback 至預設併產生日誌警告，新增診斷鏈路僅新增 `context_snapshot`/`RunDiagnosticSummary` 讀寫欄位，不改寫 `litellm_model`、`agent_litellm_model`、`openai_base_url`、LLM channel 路由或配置遷移語義。
- 補充 #1391 Phase 3 相容性說明：記錄後端診斷持久化、歷史查詢與通知回寫鏈路變更邊界與回滾策略，並補齊後端門禁級驗證要求。

### 測試

- 收斂 #1391 Phase 3 後端/API 與 Web 迴歸檢查：`./scripts/ci_gate.sh`、`test_pipeline_market_phase_context.py`、`test_analysis_api_contract.py`、`test_analysis_history.py`、`npm run lint`、`npm run build`。
- 執行 `python -c "import exchange_calendars as xcals; xcals.get_calendar('XSHG'); print('ok')"` 透過驗證，以覆蓋匯入與交易日曆初始化相容性。

## [3.18.0] - 2026-05-21

### 釋出亮點

- feat: 警告中心擴充套件到 P2-P6，補齊後臺評估、真實通知結果、業務冷卻、技術指標規則，以及自選股 / 持股 / 帳戶聯動規則。
- feat: 個股分析支援策略選擇，新增熱點題材、事件驅動、成長質量和預期重估策略，併為 HK/US 報告補充基本面、財務摘要、股東回報和關聯板塊。
- feat: 新增 Finnhub / AlphaVantage 美股資料來源介面卡，擴充套件美股日線 failover 鏈，提升美股行情獲取韌性。
- fix: 修復桌面端釋出打包、分析狀態介面、AlphaVantage 漲跌幅、持股實時估值、警告歷史去重、資料庫冷啟動和 fallback pricing 註冊等穩定性問題。

### What's Changed

- feat: Add alert-center P2-P6, Web strategy selection, HK/US fundamental context, static-report financial sections, and Finnhub / AlphaVantage US-market fallback.
- improve: Refine LiteLLM parameter recovery, yfinance currency/dividend handling, RSI calculation, market-review presentation, stock-news relevance ranking, and report table rendering.
- fix: Harden desktop packaging/update assets, completed analysis-status responses, AlphaVantage pct_chg routing, portfolio realtime snapshots, alert trigger dedupe, DatabaseManager cold start, and fallback pricing registration.
- docs/tests: Add beginner setup and settings-help docs, document compatibility/rollback boundaries, and extend regression coverage for API, alert, packaging, and release paths.

## [3.17.1] - 2026-05-16

### 釋出亮點

- fix: 桌面端 Windows / macOS 打包指令碼顯式關閉 electron-builder 自動釋出，避免 tag 構建時因缺少 `GH_TOKEN` 在本地打包完成後失敗；Release workflow 繼續負責上傳和釋出產物。

### What's Changed

- fix: Add `--publish never` to the Windows and macOS Electron packaging scripts so tag builds only create local artifacts and GitHub Actions handles release upload/publish.

## [3.17.0] - 2026-05-16

### 釋出亮點

- feat: 新增 Alert API MVP，支援警告規則 CRUD、啟停、一次性測試以及觸發/通知結果查詢，首版覆蓋 `price_cross` / `price_change_percent` / `volume_spike` 並保持 legacy 配置相容。
- feat: 通知閘道器新增 ntfy 與 Gotify 一等通道，並補齊通知降噪、靜態通道隔離、診斷、Web 測試和 GitHub Actions env 對照校驗。
- feat: Windows 桌面安裝版接入自動更新安裝鏈路，支援後臺下載、確認重啟安裝、執行時檔案備份/恢復和釋出產物後設資料校驗。
- improve: 大盤覆盤新增概念排行、人氣股、漲停池等底層資料來源，支援指數漲跌顏色語義配置，並將覆盤結果寫入歷史記錄。
- improve: Web 設定頁支援 `.env` 配置備份匯入/匯出和通知/Agent 區域區域性錯誤兜底；報告新增 `REPORT_SHOW_LLM_MODEL` 開關控制模型資訊展示。
- improve: Docker 啟動入口自動修復掛載目錄許可權並在日誌目錄不可寫時降級到控制檯，減少普通部署的手動修復步驟。
- fix: 資料來源缺憑據或連線失敗時更溫和降級，Longbridge / Pytdx 加入冷卻，資金流缺失時避免輸出高置信買進結論。
- fix: 分析與報告鏈路相容 OpenAI-compatible `content_blocks` 響應，歸一策略價格欄位，並修復大盤覆盤滾動和歷史記錄丟失問題。
- docs: 補齊通知、警告中心、桌面打包、README / 指南和 PR title 治理說明，明確多處配置相容邊界與回滾路徑。
- test: 增加 Alert API、通知降噪/路由、Docker entrypoint、資料來源預取、桌面更新鏈路和分析歷史等迴歸覆蓋。

### What's Changed

- feat: Add an Alert API MVP with rule CRUD, enable/disable, one-shot testing, trigger history, notification results, and legacy config compatibility.
- feat: Promote ntfy and Gotify to first-class notification channels with Web tests, routing, Actions integration, diagnostics, and noise control.
- feat: Add the Windows desktop auto-update install flow with runtime state backup/restore and release artifact metadata verification.
- improve: Extend market review data sources, add configurable index color semantics, and persist market review results into analysis history.
- improve: Add Web `.env` backup import/export, local settings panel error boundaries, and a report model visibility toggle.
- improve: Harden Docker startup by repairing mounted directory permissions and falling back to console logging when mounted logs are not writable.
- fix: Cool down unavailable optional fetchers, reduce noisy Longbridge/Pytdx retries, and downgrade buy advice when capital flow data is missing.
- fix: Handle OpenAI-compatible `content_blocks`, normalize strategy price fields, and recover market review scrolling/history behavior.
- docs/tests: Update notification, alert, desktop packaging, README/guide, and governance docs; add focused regression coverage for the new release paths.

## [3.16.0] - 2026-05-10

### 釋出亮點

- feat: Web 首頁新增“大盤覆盤”觸發入口、任務輪詢與完成後報告直出；首次啟動配置狀態可提示缺口並引導到系統設定。
- feat: 新增通知路由策略，支援按 report、alert、system_error 將通知收窄到指定通道；Web 設定頁支援通知通道一鍵測試。
- feat: 系統設定頁新增配置項幫助入口與多語言幫助文案基礎設施，首批覆蓋自選股、LLM 主模型、LLM 通道、飛書 Webhook 與 WebUI 監聽地址。
- improve: 大盤覆盤 API、CLI、Bot 共用 `build_market_review_runtime` 裝配路徑，補齊 `litellm_model` / `llm_model_list` 與 legacy key 回退說明。
- improve: 個股報告操作建議結合支撐/壓力、量能、籌碼與主力資金流校準，減少買進/賣出劇烈切換，並補強 Agent 決策兜底。
- improve: Docker 映象支援非 root 使用者執行，LiteLLM 依賴約束放寬到後續安全 1.x 修復版本。
- fix: 修正 LLM 通道測試中 `Model disabled`、provider blocked 等錯誤分類，避免被誤報為網路異常。
- fix: 港股日線跳過不支援港股的內建歷史資料來源；北交所 `BJ` 字首與 `.BJ` 字尾程式碼校驗保持一致。
- fix: Web 大盤覆盤按鈕可觀測性、Windows fallback 鎖程序探測和催化線索展示更穩健。
- docs: 新增文件中心與配置幫助維護說明，清理 README、完整指南與配置指南中的臨時 PR/文件同步說明。

### What's Changed

- feat: Add a Web home market-review trigger with task polling and inline report display; setup status now points users to missing configuration.
- feat: Add notification routing by report, alert, and system_error; add one-click notification channel testing in Web settings.
- feat: Add settings field help infrastructure with multilingual help text for the first batch of core configuration fields.
- improve: Share `build_market_review_runtime` across API, CLI, and Bot market review paths; document `litellm_model` / `llm_model_list` and legacy key fallback behavior.
- improve: Calibrate stock advice with support/resistance, volume, chips, and main-force capital flow; strengthen Agent decision fallback behavior.
- improve: Run Docker images as a non-root user and relax LiteLLM constraints to allow safe future 1.x fixes.
- fix: Classify `Model disabled`, provider blocked, and related LLM channel test errors more accurately instead of reporting them as generic network failures.
- fix: Avoid unsupported built-in historical providers for Hong Kong daily data; align Beijing Stock Exchange `BJ` prefix and `.BJ` suffix validation.
- fix: Improve Web market-review observability, Windows fallback lock probing, and market catalyst snippet rendering.
- docs: Add the documentation index and settings-help maintenance guide; remove temporary PR/doc-sync notes from README and user-facing guides.

## [3.15.0] - 2026-05-05

### 釋出亮點

- LLM 通道配置體驗繼續升級：新增 Anspire OpenAI-compatible 閘道器接入，並補齊常用服務商預設、官方來源、能力標籤、配置注意事項和 GitHub Actions 顯式對映。
- Web LLM 配置檢測更可診斷：細分錯誤 reason，並支援使用者顯式觸發 JSON、tools、vision、stream 執行時 smoke。
- LLM 執行時配置清理更穩健：只清理託管 provider 的失效執行時選擇，並保留 `cohere/*`、`google/*`、`xai/*` 等直連 provider 相容語義。
- 通知與 Bot 狀態可觀測性增強：自定義 Webhook 支援 JSON body 模板，Bot `/status` 展示更完整的 LLM、Agent 與通知通道狀態。
- 大盤覆盤、實時警告、Agent weak 兜底和持股估值繼續補強，降低預設值覆蓋、缺價汙染和配置排障成本。

### 新功能

- 支援 `ANSPIRE_API_KEYS` 預設接入 Anspire OpenAI-compatible 大模型閘道器，並在 LLM 通道編輯器補充 Anspire Open 預設。
- 自定義 Webhook 支援 `CUSTOM_WEBHOOK_BODY_TEMPLATE` JSON body 模板，便於適配 AstrBot、NapCat 和自建推送服務。
- 大盤覆盤結構化區塊新增大盤紅綠燈結論，基於盤面溫度輸出 green/yellow/red、核心原因和操作建議。
- EventMonitor 支援 `price_change_percent` 漲跌幅閾值規則，可按上漲或下跌方向觸發實時警告。
- Web LLM 通道編輯器新增常用服務商配置模板與預設，覆蓋 MiniMax、火山方舟、OpenAI、Claude、Gemini、Kimi、Qwen、GLM、豆包等入口。

### 改進

- Web LLM 配置檢測補充細分錯誤分類，並新增顯式觸發的 JSON/tools/vision/stream 執行時 smoke；預設測試和儲存流程不變，檢測結果僅作為當前配置的一次 best-effort 診斷。
- Bot `/status` 展示統一 LLM 主模型、Agent 模型、通道模式、YAML 配置和更多通知通道狀態。
- Web LLM 通道編輯器展示 provider 能力標籤、官方來源連結和配置注意事項提示；這些標籤僅用於配置參考，不代表執行時能力已驗證透過。
- 抽出 Web LLM provider preset 單一模板資料來源，保持現有配置儲存語義不變。
- 補齊 LLM provider channel 在 GitHub Actions 中的顯式對映，並同步 `.env` 示例與配置文件。

### 修復

- Agent weak 完整性兜底在模型缺少評分、趨勢、操作建議或 dashboard 關鍵塊時優先保留本地趨勢分析結果，並只補齊真正缺失的儀表盤欄位，避免首頁評分被預設 50 覆蓋。
- 統一持股快照輸出現價、市值、浮盈虧、收益率與價格元資訊，避免缺價或 stale 價格汙染持股估值。
- LLM 通道測試補充結構化診斷與設定頁排障提示，便於定位 provider、模型、Base URL 和鑑權配置問題。
- 明確 runtime 清理相容邊界：僅對託管 provider（`gemini`、`vertex_ai`、`anthropic`、`openai`、`deepseek`）觸發儲存前失效值清理，`cohere/*`、`google/*`、`xai/*` 直連值按 legacy 相容路徑保留，不做無提示遷移或覆寫。
- 將 MiniMax 預設調整為官方 OpenAI-compatible Base URL 和當前模型示例，並補充 MiniMax、火山方舟、LiteLLM 相容來源與回退說明。
- 移除截圖識別對 Gemini 3 Vision 模型的過時降級邏輯，預設推斷改用當前 Gemini 模型配置。

### 文件

- 完善 LLM provider 配置文件，補充配置方式選擇、Actions 變數對照、執行時檢測邊界、錯誤 reason 排障和回滾路徑（#1180）。
- 補充 LLM 通道編輯器的官方來源、依賴相容視窗、儲存時的執行時模型清理規則，以及舊配置回退路徑說明。
- 為 `cohere/*`、`google/*`、`xai/*` 直連語義補充官方 provider/model 說明、`litellm>=1.80.10,<1.82.7` 相容依據引用，並明確示例模型名僅為配置保留行為說明而非可用性背書。
- 明確 `price_change_percent` 事件警告僅為配置與執行時規則擴充套件，未變更模型/provider/base URL/LiteLLM 相容語義；回退路徑為關閉/移除 Event Monitor 配置。
- 同步 README、DEPLOY、full-guide、Anspire、AIHubMix 與 SerpAPI 相關說明，統一外鏈、配置口徑和評審一致性說明。

### 測試

- 補齊 AI 配置頁與 `task_queue` 的 LLM 執行時清理/同步迴歸證據：恢復通道模型時保留 fallback、編輯模型列表期間不靜默清空執行時選擇，通道無可用模型時清理失效 runtime 引用，並覆蓋 legacy key 與 `cohere/*`、`google/*`、`xai/*` 直連 provider 保留語義。
- 覆蓋 Web LLM 配置檢測的細分錯誤分類，以及 JSON、tools、vision、stream 執行時 smoke 的顯式觸發路徑。

## [3.14.2] - 2026-04-30

### 釋出亮點

- 大盤覆盤擴充套件到港股，並讓 Bot `/market` 與 CLI/排程入口使用一致的交易日過濾語義。
- 問股與 Agent 鏈路增強配置缺失、決策 fallback 和多策略選擇體驗。
- LLM 與分析報告鏈路提升穩定性：非法 JSON 響應會繼續嘗試備用模型，LiteLLM DEBUG 日誌預設降噪。
- 新增只讀首次啟動配置狀態介面，為後續配置嚮導和 smoke run 奠定基礎。

### 新功能

- 大盤覆盤支援港股市場：`MARKET_REVIEW_REGION` 新增 `hk` 選項；`both` 擴充套件為 A股+港股+美股，並新增港股指數（HSI/HSTECH/HSCEI）覆盤鏈路。
- 新增只讀首次啟動配置狀態介面 `GET /api/v1/system/config/setup/status`，用於識別 LLM、Agent、自選股、通知和本地儲存配置缺口；該介面不會過載執行時、寫入 `.env` 或建立資料庫檔案。

### 改進

- 問股頁面支援組合選擇多個 Agent 策略。

### 修復

- Bot `/market` 命令複用 `get_open_markets_today()` / `compute_effective_region()` 做交易日過濾：結果作為 `override_region` 透傳給 `run_market_review`；若結果為空字串則跳過覆盤並推送“今日相關市場休市”，與 CLI/排程入口行為一致。
- 問股 Agent 在未配置可用 LLM 時保留後端真實錯誤原因並維持 `done.success=false` 失敗語義，避免前端把配置缺失誤當成成功回答。
- Agent 模式未生成有效決策儀表盤時保留本地趨勢分析的評分、趨勢和操作建議，並將強買/強賣 fallback 歸一到相容的 `buy`/`sell` 決策型別，避免首頁結果被 `50 / 觀望 / 未知` 預設值覆蓋。
- 持股快照現價缺失時不再靜默回退為持股成本；當天快照優先使用歷史收盤價，僅在缺失時使用實時價 fallback，缺價持股不再汙染市值與未實現盈虧彙總，併為持股明細返回價格來源、日期、stale 與缺價狀態。
- 分析 Prompt 在注入 `trend_analysis` 前按最終 `trend_status` / `ma_alignment` 清洗互斥理由：空頭結構移除看多理由、多頭結構移除空頭結構風險，並在事件/技術衝突與異常放量（>10 倍）時強制提示“事件先行、技術待確認”與量能降權。
- LLM 返回非 JSON 響應時同樣觸發備用模型切換：主模型成功返回但無法解析 JSON 時，不再立即降級為純文字 fallback，而是依次嘗試 `LITELLM_FALLBACK_MODELS` 中的備用模型；所有模型均無法返回合法 JSON 時，再降級為文字 fallback。
- LiteLLM 內部 DEBUG 日誌預設壓低到 WARNING，避免流式生成時 token 級日誌汙染 `stock_analysis_debug_*.log`；如需排查 LiteLLM 內部細節，可臨時設定 `LITELLM_LOG_LEVEL=DEBUG`（Fixes #1156）。

### 文件

- 補充 LLM 配置指南與 FAQ，明確問股 Agent 對 `LITELLM_CONFIG` / `LLM_CHANNELS` / legacy `GEMINI_*` `OPENAI_*` `ANTHROPIC_*` 的相容優先順序、回退路徑與“不靜默遷移舊配置”的結論。

### 測試

- 新增 `tests/test_bot_market_command.py`，覆蓋 `MARKET_REVIEW_REGION=both` + open markets `{"cn","us"}` / `{"cn","hk"}` 的 `override_region` 透傳斷言，並覆蓋全市場休市跳過與關閉交易日檢查路徑；新增 `tests/test_yfinance_hk_indices.py` 覆蓋港股指數符號對映與部分/全部失敗降級路徑。
- 補齊 `task_queue` 輕量匯入 stub 的股票程式碼規範化函式，恢復 `tests/test_task_queue_config_sync.py` 收集與執行。

## [3.14.1] - 2026-04-26
- [測試] 修正大盤覆盤 prompt 測試對“明日交易計劃”標題的斷言，並同步桌面端版本號，恢復釋出 gate。

## [3.14.0] - 2026-04-26

### 釋出亮點

- 📊 **大盤覆盤升級為盤後工作臺式結構** — A 股覆盤固定輸出盤面溫度、指數明細、板塊 Top 表、新聞催化、明日交易計劃和風險提示，減少純文字覆盤的重複與空泛。
- 🖥️ **桌面端新增 GitHub Release 更新提醒** — Windows/macOS 桌面端啟動後自動檢測新版本，也可從設定頁手動檢查並跳轉下載頁。
- 🤖 **Pipeline Agent 資料載入大幅降噪** — K 線工具改為 DB-first 並預熱 240 天曆史資料，避免同一只股票重複 HTTP 請求。
- 🐳 **Docker 釋出鏈路整理** — 釋出工作流收斂為正式釋出與手動補發兩條路徑，官方 Docker Hub 映象名統一為 `zhulinsen/daily_stock_analysis`。
- 🔧 **LLM 通道與 DeepSeek V4 配置補強** — GitHub Actions 定時分析補齊多通道變數透傳，DeepSeek 官方通道預設與示例同步到 V4。
- 🧩 **桌面端靜態資源一致性校驗** — 打包鏈路和執行時都能更早發現靜態資源錯配，降低 Release 包白屏排查成本。

### 新功能

- 🏠 **Web 首頁歷史報告區新增重新分析入口** — 支援基於原始 prompt 重做同一只股票同日期的分析。
- 🖥️ **Windows/macOS 桌面端新增 GitHub Release 更新提醒** — 啟動後自動檢測新版本，並支援從設定頁手動檢查後跳轉下載頁。

### 改進

- 📊 **A 股大盤覆盤報告改為結構化盤後工作臺版式** — 固定輸出盤面溫度、指數明細、板塊 Top 表、新聞催化和明日交易計劃。
- 🐳 **Docker 釋出工作流收斂** — 更清晰地區分正式釋出與手動補發鏈路，並統一官方 Docker Hub 映象名為 `zhulinsen/daily_stock_analysis`。
- 🤖 **Agent 日線工具優先複用本地快取** — 同時持久化新獲取的日線與新聞情報，減少重複資料來源呼叫。

### 修復

- 🤖 **Pipeline Agent K 線工具 DB-first 載入** — `get_daily_history` / `analyze_trend` / `calculate_ma` / `get_volume_analysis` / `analyze_pattern` 改為優先讀取本地 DB，消除同一只股票 9x5=45 次重複 HTTP 請求（Fixes #1066）。
- 🤖 **Pipeline Agent 執行前按需預熱 240 天 K 線歷史到 DB** — 正常情況下 K 線工具呼叫無需重複網路請求。
- 🕒 **凍結 `target_date` 並透過 ContextVar 透傳到 Pipeline Agent K 線工具執行緒** — 消除跨收盤邊界時間漂移。
- 🪟 **Windows 桌面端後端日誌轉抄編碼修復** — 轉抄 stdout/stderr 時優先使用 UTF-8，併相容原生代碼頁回退，避免中文日誌亂碼。
- ⚙️ **GitHub Actions 每日分析工作流補齊 LLM 通道變數透傳** — 支援 `LLM_CHANNELS`、多 Key 與常用 `LLM_<NAME>_*`，避免本地可用的多模型配置在雲端定時任務中失效（Fixes #1063, #872）。
- 📈 **歷史報告詳情介面修正 `change_pct` 取值** — 使用 `is None` 判斷避免把 0.0（平盤）當作缺失值丟棄，移除錯誤的 `change_60d` 兜底，並在缺失時回退到原始實時行情欄位（Fixes #1084）。
- 🔧 **DeepSeek 官方通道預設與示例配置同步到 V4** — 保留 legacy `deepseek-chat` 預設值並增加廢棄提示，同時修正模型發現後舊執行時選擇導致儲存失敗的問題（Fixes #1108, #1109）。
- 🧩 **桌面端打包鏈路新增靜態資源一致性檢查** — `scripts/check_static_assets.py` 會在源 `static/` 與 PyInstaller 產物中校驗 `index.html` 引用的資源是否真實存在，執行時也會在錯配時寫入明確日誌，避免重現 Release 包開啟後白屏（Refs #1064 / #1065 / #1050）。
- 🧩 **後端 `/assets/*` 改為顯式路由託管** — 資源缺失時返回與請求副檔名匹配的 `text/javascript` / `text/css` 404，減少預設 JSON 錯誤響應帶來的排查誤導（Refs #1064）。
- 🌙 **`kimi-k2.6` 自動使用固定溫度** — 主分析、大盤覆盤和 Agent 呼叫該模型時自動使用 `temperature=1.0`，避免模型拒絕預設溫度請求（Fixes #1102）。

### 文件

- 🐳 **補充官方 Docker 映象使用說明** — 增加映象拉取、`docker run` 用法與 `.env` / 資料目錄對映說明，不再只覆蓋 Compose 部署路徑。
- 📨 **修正飛書自定義機器人 Webhook 示例** — `feishu_sender.py` 中的示例改為 interactive card JSON，並補充飛書自動化 Webhook 觸發器配置教程。
- 📚 **最佳化根 README 結構** — 保留首頁級功能特性、技術棧、快速開始、推送效果、Web、Agent、贊助商和新聞源入口，將細配置、交易紀律和基本面語義收口到完整指南，並將 Docker 徽章指向官方映象頁。
- 🌐 **同步英文與繁中 README 的精簡入口結構** — 同時補齊完整指南中的 LLM 用量 API 與持股管理說明。
- 🤝 **調整 AI 協作與 PR 模板中的 README 維護規則** — 明確 README 非必要不更新，細節優先進入專題文件。

### 測試

- 🧪 **穩定市場覆盤相關測試的 LiteLLM stub 行為** — 避免本機安裝的 LiteLLM 在測試收集順序變化時影響市場覆盤單元測試。
- 🧪 **pytest 預設跳過前端依賴目錄** — 本地存在 `apps/dsa-web/node_modules` 時不再被後端測試遞迴掃描，避免釋出前 gate 被無關目錄拖慢。

## [3.13.0] - 2026-04-21

### 釋出亮點

- 🌉 **長橋 OpenAPI 資料來源接入** — 美股/港股行情優先使用 Longbridge，YFinance / AkShare 自動兜底；未配置時行為不變。
- 📈 **Tushare 港股全鏈路擴充套件** — 港股日線透過 `hk_daily` 獲取；籌碼分佈對港股返回 `None`；換算單位跟隨港股口徑，不再套用 A 股手/千元規則。
- 🔍 **Anspire Search 語義搜尋接入** — 配置 `ANSPIRE_*` 後即可使用 Anspire Search 獲取實時行情及資訊，未配置時完全透明。
- 🚀 **普通分析鏈路支援 LLM 流式生成** — 首頁任務 SSE 新增 `task_progress` 事件，進度更細化；不支援流式的 provider 自動回退到非流式呼叫。
- 🤖 **Web 通道編輯器支援按需拉取可用模型列表** — `/v1/models` 統一模型發現入口，多選寫回 `LLM_{CHANNEL}_MODELS`，拉取失敗時保留手動輸入降級。
- 🛡️ **Agent 穩定性與預算護欄全面補強** — `AGENT_MAX_STEPS` 語義統一、技能降級不中斷管線、SSE 異常透傳、技能載入 warning 日誌補齊。
- 🛠️ **SQLite 寫入鏈路原子化** — 批次原子 upsert + WAL + `busy_timeout` + 有限寫入重試，顯著降低批次分析併發鎖競爭。

### 新功能

- 🌉 **整合 Longbridge OpenAPI 作為美股/港股可選資料來源**（fixes #981）— 配置 `LONGBRIDGE_*` 後優先使用長橋獲取日線與實時行情，YFinance / AkShare 兜底；未配置時行為與此前一致。聯調使用 `tests/longbridge_live_smoke.py`（手動指令碼，不參與 pytest 收集）。
- 📈 **Tushare 支援港股日線查詢** — 配置 Tushare 憑證後呼叫 `hk_daily` 介面獲取港股資料；許可權不足時丟擲異常，與原流程一致。
- 🔍 **整合 Anspire Search 可選語義搜尋後端** — 配置 `ANSPIRE_*` 可使用 Anspire Search 獲取實時行情及新聞資訊；未配置時行為與此前一致。聯調使用 `tests/test_anspire_search.py`（手動指令碼）。
- 🚀 **普通分析鏈路支援 LiteLLM 流式生成與更細任務進度** — 股票分析在 LLM 階段優先嚐試 `stream=True` 並在服務端累積 chunk，首頁任務 SSE 新增 `task_progress` 事件與更細的 `message/progress` 更新；僅在最終 JSON 解析成功後持久化歷史報告；不支援流式的 provider 自動回退到非流式呼叫。
- 🤖 **Web AI 模型配置支援按通道獲取可用模型列表** — 通道編輯器支援呼叫 `/v1/models` 拉取可用模型，並以多選方式寫回 `LLM_{CHANNEL}_MODELS`；拉取失敗時保留手動輸入作為降級路徑。

### 改進

- 🔎 **SerpAPI 正文補抓範圍收斂** — 自然搜尋結果不再逐條同步抓取網頁正文；僅對極少數高位且摘要不足的結果做延遲補抓，優先複用 SerpAPI 已返回的結構化摘要，降低搜尋鏈路尾延遲與慢站點放大風險。
- 🤖 **LLM 接入體驗簡化** — 面向使用者的 AI 模型接入文案統一為"主模型 / Agent 主模型 / 備選模型 / 模型通道"，不再把 LiteLLM 當作普通使用者必學概念，現有 `LITELLM_*` / `LLM_CHANNELS` 配置鍵保持相容。
- 🧠 **IntelAgent 新增公司公告搜尋與主力資金流工具** — 增加上交所/深交所/cninfo 公告搜尋維度與 `get_capital_flow` 工具，修復 Agent 模式下公告和資金流資料經常缺失的問題。
- 📦 **後端股票名稱解析優先複用 `stocks.index.json`** — 懶載入快取前端靜態索引，純後端/缺失靜態資源場景靜默降級回 `STOCK_NAME_MAP` 與原有資料來源回退鏈路。
- 📊 **TushareFetcher 港股單位適配** — `get_chip_distribution` 對港股直接返回 `None`（港股暫不支援籌碼分佈）；`_normalize_data` 對港股（`hk_daily`）不再做 A 股手→股、千元→元的縮放，與 Tushare 港股欄位語義一致。
- ⏱️ **Agent 超步數錯誤增加 `AGENT_MAX_STEPS` 調整提示** — 幫助使用者自助排查步數限制問題。
- ⚙️ **GitHub Actions 分析任務超時支援 `vars` 配置** — `daily_analysis.yml` 任務超時從 repository variables 讀取，無需修改程式碼即可調整執行超時上限（fixes #1014）。

### 修復

- 📣 **大盤覆盤鏈路接入 `REPORT_LANGUAGE`** — `REPORT_LANGUAGE=en` 時，A 股/合併覆盤的 Prompt、章節標題、模板兜底文案與通知包裝標題統一輸出英文，避免英文正文搭配中文標題的混排問題。
- 📈 **EfinanceFetcher 指數開盤價對映相容**（fixes #1043）— `get_main_indices()` 的開盤價對映改為相容 `今開 → 開盤 → open`，修復部分 efinance 版本下指數開盤價被讀成缺失值的問題。
- 🤖 **AGENT_MAX_STEPS 語義統一**（fixes #1026）— 在 orchestrator 多 Agent 模式下明確為"各子 Agent 步數上限而非硬覆蓋"；TechnicalAgent 等高預設值 Agent 會被封頂，低預設值 Agent 保持原值；使用者主動調高（>10）時統一覆蓋所有子 Agent。修復了使用者設定 12 但 TechnicalAgent 仍以預設 6 步執行並報 "Agent exceeded max steps" 的問題。
- 🛡️ **Specialist（Skill）Agent 失敗改為優雅降級** — 技能 Agent 失敗不再中斷整個分析管線，與 intel/risk 保持相同的降級策略。
- 🔧 **MiniMax-M2.7 連線測試修復** — 修復 LLM 通道連線測試在 MiniMax-M2.7 下返回 "Empty response" 的問題；將 `max_tokens` 上限從 8 提升至 256 以容納思考過程，並新增 `content_blocks` 格式解析邏輯。
- 📊 **移除 `sentiment_score` 範圍約束**（fixes #942）— 移除 `HistoryItem` 與 `ReportSummary` 響應 Schema 中 `sentiment_score` 的 `ge=0/le=100` 約束，歷史庫中儲存的超範圍值不再觸發 Pydantic ValidationError。
- 🖥️ **WebUI 前端資源缺失時發出明確警告** — `webui_frontend.py` 在 `static/index.html` 存在但 `static/assets/` 缺失時發出 warning，避免 CSS/JS 資源缺失導致頁面異常變大卻無從排查（fixes #944）。
- 🔗 **分析管線可選服務降級初始化** — `StockAnalysisPipeline` 搜尋服務與社交輿情服務任一初始化異常時，記錄 warning 並以禁用狀態繼續執行，避免外部依賴抖動阻塞主分析鏈路。
- 🖥️ **桌面端版本展示統一讀取 `package.json`** — 統一讀取 `apps/dsa-desktop/package.json`，移除 preload 中硬編碼的 `0.1.0`，設定頁展示真實桌面端版本；修復版本號顯示錯誤（fixes #1048）。
- 🐋 **港股名稱獲取失敗修復**（fixes #940）— 修復主資料來源欄位缺失時無法正確回退到備用欄位獲取港股名稱的問題。
- 🔄 **SSE 任務流斷開時 `CancelledError` 正確 re-raise**（fixes #967）— 修復 SSE 流中斷時異常被靜默吞掉導致故障無日誌可查的問題。
- 🔄 **Agent SSE 清理階段後臺任務異常正確上報**（fixes #969）— 流結束時後臺執行器異常現在正確記錄並上報，避免錯誤無法感知。
- 🔇 **技能載入異常補充 `logger.warning` 日誌**（fixes #970）— 在 `ask.py`、`skills/aggregator.py`、`skills/router.py` 的靜默 except 塊補充日誌，確保技能列表為空時有日誌可查。
- 🛠️ **SQLite 寫入鏈路原子化**（fixes #878）— `stock_daily(code,date)` 使用批次原子 upsert；檔案型 SQLite 連線預設啟用 WAL + `busy_timeout` + 有限寫入重試；"新增數"改按本次真正插入視窗計算。
- 💰 **多 Agent / 單 Agent 預算護欄語義統一** — 剩餘預算低於最小閾值時主動跳過並降級；已完成階段可構建降級報告時返回 `success=True` 並攜帶非空內容，否則返回 `success=False`。
- ⚙️ **GitHub Actions `daily_analysis.yml` 補齊 `REPORT_LANGUAGE` 注入**（fixes #1013）— 修復使用者在 Secrets/Variables 中配置 `REPORT_LANGUAGE` 後不生效的問題。
- 📊 **任務狀態 API 補齊實時價格欄位**（fixes #983）— `GET /api/v1/analysis/status/{task_id}` 從資料庫回填已完成任務時補齊 `current_price` / `change_pct`，修復首頁報告股票名旁不顯示實時價格的問題。
- 📅 **非交易日資料返回最近交易日**（fixes #1009）— 修復非交易日（週末/節假日）籌碼分佈與板塊排行返回倒數第二個交易日資料的問題，現在正常返回最近交易日資料。
- 🔍 **A 股資訊搜尋恢復中文優先** — `search_stock_news()` 在首個 provider 主要返回英文資訊時繼續嘗試後續引擎，並將同批結果中的中文資訊排到前面；非美股查詢不再預設沿用 Brave 的 `en/US` 區域語言偏好。
- 📨 **飛書群機器人通知支援簽名校驗** — 飛書通知現在支援 `FEISHU_WEBHOOK_SECRET` / `FEISHU_WEBHOOK_KEYWORD`；Web 設定與文件明確區分 Webhook 推送模式和 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 應用模式，降低誤配風險。
- ⚡ **LLM 適配層新增 `RateLimitError` 和 `ContextWindowExceeded` 檢測** — 識別並處理速率限制與上下文視窗超出錯誤，提升分析鏈路在高負載或長文字場景下的健壯性（fixes #1002）。

### 測試

- 🧪 **TushareFetcher 港股相關單元測試** — 新增 `get_chip_distribution` 籌碼分佈獲取與 `_normalize_data` 港股/A 股/ETF 單位處理的單元測試，覆蓋港股特殊路徑。

### 文件

- 📘 **DEPLOY.md 補充 UI 元素異常變大排查步驟** — 新增重建 Docker 映象或手動執行 `npm run build` 的排查指南；`deploy-webui-cloud.md` 同步更新。
- 📨 **飛書 Webhook 配置說明補全** — 強調 `FEISHU_WEBHOOK_URL` 是群通知必填項、簽名校驗須兩端同時啟用或關閉、`FEISHU_APP_SECRET` 僅用於應用/Stream Bot 模式；`.env.example` 補充內聯註釋；同步英文指南。
- 🤝 **FAQ 補充 Ollama 連線失敗排障條目（Q12c）** — 覆蓋服務未啟動、URL 配置錯誤、模型字首缺失、模型未下載、遠端防火牆等 5 個檢查點（fixes #854）。
- 🌉 **README 補充長橋資料來源使用說明** — 中/英/繁 README 明確長橋"首選 / 兜底 / 未配置不呼叫"邊界；`docs/` 內相對路徑連結修復；`LONGBRIDGE_PRINT_QUOTE_PACKAGES` 配置與程式碼及 `.env.example` 對齊。
- 🐋 **Docker 安裝場景版本說明** — 補充最小化文件，明確 Docker 安裝場景下應以 Git tag / 映象 tag 判斷版本（fixes #1091）。

## [3.12.0] - 2026-04-01

### 釋出亮點

- 📊 **回測頁新增"次日驗證"檢視** — 可按股票與日期範圍檢視 AI 預測 vs 次日實際漲跌，複用歷史分析與 1 日回測結果，快速驗證分析準確率。
- 🔧 **LLM 接入體驗簡化** — 使用者側文案統一收口為"主模型 / 備選模型 / 模型通道"，不再把 LiteLLM 當作普通使用者必學概念，現有配置鍵保持相容。
- 🐳 **Docker / WebUI 執行時穩態補強** — 修復系統設定儲存後配置不生效、啟動早期日誌缺失、預構建靜態資源複用等問題，降低容器化部署的運維摩擦。
- 🔒 **安全與併發穩定性同步增強** — Discord 入站 Webhook 補齊 Ed25519 驗籤，修復併發執行時共享狀態未加鎖、單股推送模式通知併發複用等問題。
- 🖥️ **桌面端與定時任務細節打磨** — Windows 安裝器支援自選安裝目錄，內建定時排程器感知執行中 SCHEDULE_TIME 變更，斷點續傳改按市場時區判斷。

### 新功能

- 📊 **回測頁新增"次日驗證 / 1 日視窗"檢視** — 可按股票程式碼與分析日期範圍檢視 AI 預測、次日實際漲跌及篩選區間準確率，複用歷史分析與 1 日回測結果實現。
- 🏷️ **Web 設定頁新增版本資訊卡片** — `apps/dsa-web` 現在會在構建時注入前端包版本與構建時間，系統設定頁新增只讀"版本資訊"區塊，展示 `WebUI 版本 / 構建標識 / 構建時間`；當 `package.json` 仍為佔位版本 `0.0.0` 時，會自動回退為構建標識，方便 Docker 重建後快速確認當前靜態資源是否已經生效。
- 🪟 **Windows 桌面安裝器支援自選安裝目錄** — 安裝器改為支援在安裝嚮導中自定義安裝目錄，安裝到非預設磁碟機代號後仍沿用現有打包態目錄邏輯在安裝目錄旁讀寫 `.env`、`data/stock_analysis.db` 和 `logs/desktop.log`，同時保留 `win-unpacked` 免安裝分發方式。安裝器僅支援當前使用者安裝、已禁用管理員提權（`allowElevation: false`），並透過 NSIS `.onVerifyInstDir` 阻止選擇系統保護目錄。

### 改進

- 🔎 **SerpAPI 正文補抓範圍收斂** — 自然搜尋結果不再逐條同步抓取網頁正文；現在僅對極少數高位且摘要明顯不足的結果，在更短超時預算內做延遲補抓，並優先複用 SerpAPI 已返回的結構化摘要，降低搜尋鏈路尾延遲與慢站點放大風險。
- 🤖 **LLM 接入體驗簡化** — 面向使用者的 AI 模型接入文案已統一收口為"主模型 / Agent 主模型 / 備選模型 / 模型通道 / 高階模型路由配置"；Web 設定頁、配置後設資料、校驗提示與中英文文件不再把 LiteLLM 當作普通使用者預設必學概念，現有 `LITELLM_*` / `LLM_CHANNELS` 配置鍵仍保持相容。

### 修復

- 🚀 **啟動早期失敗時暴露真實根因** — `python main.py` 現在透過 stderr 暴露真實根因，bootstrap 階段不再向硬編碼 `logs/` 目錄寫入檔案日誌，檔案日誌推遲到 `config.log_dir` 可用後建立，避免健康啟動在非預期路徑殘留日誌檔案。
- 🐳 **Docker WebUI 執行時優先複用預構建靜態資源** — `prepare_webui_frontend_assets()` 現在會先檢查映象內已有的 `static/index.html` 是否可直接複用；當容器執行時不包含 `apps/dsa-web` 原始碼目錄且未安裝 `npm` 時，也不會誤報"未找到前端專案，無法自動構建"，從而恢復 Docker 部署後的 WebUI 開啟能力。
- 🐳 **Docker WebUI 系統設定儲存後配置生效** — Docker 場景下 WebUI 儲存 `STOCK_LIST`、`SCHEDULE_ENABLED`、`SCHEDULE_TIME`、`SCHEDULE_RUN_IMMEDIATELY`、`RUN_IMMEDIATELY` 後，`Config` 會優先讀取持久化 `.env` 中的新值，避免被容器建立時注入的舊環境變數覆蓋。
- 📈 **市場覆盤 LLM max_tokens 提升** — 市場覆盤生成鏈路將 LLM `max_tokens` 從 `2048` 提升到 `8192`，降低長覆盤輸出因 `MAX_TOKENS` 提前截斷導致內容未完成的機率。
- ⏰ **內建定時排程器感知 SCHEDULE_TIME 執行時變更** — 排程器現在會在執行中感知 WebUI 儲存後的 `SCHEDULE_TIME` 變化，並在下一輪檢查時重綁 daily job。
- 🪟 **Windows Release 通道編輯器保留 MiniMax 模型字首** — 通道模式下填寫 `minimax/<模型名>` 時，後端歸一化與 Web 設定頁執行時模型列表都會保留該值原樣，不再誤改寫成 `openai/minimax/<模型名>`。
- 🤖 **Discord 入站 Webhook 補齊 Ed25519 驗籤** — `DiscordPlatform` 現在會基於 `X-Signature-Ed25519`、`X-Signature-Timestamp` 和原始請求體校驗 Discord Interaction 簽名；缺失簽名頭、公鑰格式非法或簽名不匹配時直接拒絕請求，同時對 timestamp 做 ±5 分鐘時效視窗校驗以防禦重放攻擊。
- ⚙️ **STOCK_GROUP_N / EMAIL_GROUP_N 配置關係明確化** — 明確與 `STOCK_LIST` 的關係，並在配置校驗中對超出 `STOCK_LIST` 的郵件分組給出 warning。
- 🗓️ **斷點續傳改按市場時區和交易日曆判斷**（fixes #880）— 股票資料存在性檢查不再直接使用伺服器自然日，而是按 A 股 / 港股 / 美股各自市場時區解析"最新可複用交易日"。
- 📨 **單股推送模式不再併發複用共享通知例項** — `StockAnalysisPipeline.run()` 現在會保留個股分析併發，但把 `SINGLE_STOCK_NOTIFY=true` 下的即時通知挪到結果收集側序列傳送。
- 🔇 **實時行情降級提示收口為單次警告** — 分析主流程獲取股票名稱時不再提前觸發一次實時行情查詢，只有在全部資料來源都不可用時才提示已降級為歷史收盤價繼續分析。
- 🔍 **A 股中文資訊搜尋恢復中文優先** — `search_stock_news()` 現在會在首個 provider 主要返回英文資訊時繼續嘗試後續引擎，並將同批結果中的中文資訊排到前面。
- 🔒 **併發執行時共享狀態補齊統一加鎖** — 修復併發執行時共享狀態缺少統一加鎖的問題，避免多執行緒場景下的資料競爭。

### 測試

- 🧪 **補充設定頁版本資訊迴歸測試** — 新增 Web 設定頁版本資訊渲染斷言，並覆蓋佔位版本 `0.0.0` 自動回退為構建標識的邏輯。
- 🧪 **UI 治理與關鍵路徑迴歸補強** — 補充 `SidebarNav`、`ChatPage`、`BacktestPage` 等元件測試，並新增 UI governance 守衛，持續防止互動元素重新引入原生 `title` 屬性或舊 `input-terminal` 樣式迴流。同步更新 smoke / markdown drawer 相關驗證，覆蓋主題升級後的關鍵主鏈路。

## [3.11.0] - 2026-03-27

### 釋出亮點

- 🎨 **Web 工作臺完成一輪 UI 統一與雙主題升級** — 首頁、問股、回測、持股和設定頁進一步收口到統一設計 token、輸入表面和狀態表達；新增完整淺色主題，並支援淺色 / 深色一鍵切換與持久化儲存。
- 🤖 **Bot / Agent 能力重新補回主分支** — 恢復 `/history`、`/strategies`、`/research` 等命令，`/ask` 繼續支援多股對比與組合視角；Deep Research、事件監控與 schedule 輪詢鏈路重新接回主線能力。
- 🔒 **安全性與執行穩態同步補強** — 修復 `X-Forwarded-For` 限流繞過風險，恢復 LiteLLM 官方 PyPI 安裝路徑，Tushare 初始化不再依賴本地 SDK，降低 Docker、桌面打包和環境重建時的脆弱點。
- 🖥️ **日常使用細節繼續打磨** — 修復首頁港股自動補全提交、登入頁首屏主題閃爍、歷史長股票名重疊，以及 Telegram Markdown 解析失敗時整條通知傳送中斷等問題。

### 新功能

- 🎨 **全新淺色主題與雙主題切換上線** — Web 工作臺新增完整淺色主題，並支援在側邊欄中一鍵切換淺色 / 深色模式；主題選擇會持久化儲存，重新整理頁面後仍保持當前偏好。此次升級不是區域性配色微調，而是對卡片層級、邊界對比、輸入表面、狀態提示和頁面背景做了一整套 light theme 重繪。
- 🤖 **補回主分支缺失的 Agent / Bot 能力** — `#648` / `#649` 已重新補回 `main`：Bot 恢復 `/history`、`/strategies`、`/research`，`/ask` 保留多股對比與組合視角；Deep Research 與 Event Monitor 的配置重新在 Web 設定頁可見並可編輯，schedule 模式也重新接入事件警告輪詢。

### 改進

- 🖥️ **核心頁面統一到同一套工作臺視覺語言** — `Home / Chat / Backtest / Portfolio / Settings` 進一步收口到共享設計 token、`input-surface` 輸入體系、空態/錯誤態表達和抽屜遮罩語義，減少頁面之間的視覺割裂與區域性私有樣式漂移。
- 💬 **問股互動可達性與反饋增強** — 問股頁補強了會話匯出、通知傳送、訊息複製、歷史刪除與追問上下文提示；AI 回覆操作不再過度依賴 hover，觸屏裝置和小屏場景下也能直接觸達關鍵按鈕。
- 📊 **回測與持股頁表面和狀態表達繼續標準化** — 回測頁篩選控制元件、布林狀態、結果表格與彙總卡片統一到共享輸入/狀態原語；持股頁的匯入反饋、匯率重新整理提示、空態與警示資訊進一步歸口到共享元件，減少頁面級重複實現。
- 🧭 **導航與頁面殼層協同最佳化** — 側邊欄主題切換、問股完成角標、移動端抽屜遮罩和主內容滾動契約進一步統一，首頁、問股和回測在桌面端與移動端的切頁體驗更穩定。

### 測試

- 🧪 **UI 治理與關鍵路徑迴歸補強** — 補充 `SidebarNav`、`ChatPage`、`BacktestPage` 等元件測試，並新增 UI governance 守衛，持續防止互動元素重新引入原生 `title` 屬性或舊 `input-terminal` 樣式迴流。同步更新 smoke / markdown drawer 相關驗證，覆蓋主題升級後的關鍵主鏈路。

### 修復

- 🌗 **Web 首屏預設主題預設為深色** — `apps/dsa-web/index.html` 現在會在 React 掛載前讀取本地儲存的主題偏好；若沒有已儲存值，則立即給 `<html>` 預設 `dark` 並同步 `color-scheme`，避免首頁和登入頁首屏先閃出淺色主題。
- 🔐 **登入頁獨立主題層收口** — 登入頁輸入框、標籤、切換按鈕和按鈕文案現在使用獨立的 `--login-*` 視覺 token，不再繼承全域性淺/深主題文字色；即使瀏覽器快取了淺色主題，登入頁仍保持穩定的深色視覺與青色密碼輸入表現，避免密碼圓點和文案落成黑色。
- 🖥️ **首頁港股程式碼輸入修復** — Web 首頁分析輸入框現在可正確接受港股程式碼與自動完成選中的港股項，補齊 `00700.HK` / `HK00700` 等格式識別，避擴音交時誤報“請輸入有效的股票程式碼或股票名稱”。

- 🔒 **認證限流 X-Forwarded-For 取值修復（CWE-345）**（#841 / #842）— `get_client_ip()` 從取 `X-Forwarded-For` 最左值改為最右值，防止攻擊者透過偽造首部旋轉限流桶繞過暴力破解保護；僅影響 `TRUST_X_FORWARDED_FOR=true` 且單層可信反向代理的部署場景，多級代理環境需按部署文件評估配置。
- 📦 **恢復 LiteLLM 官方 PyPI 安裝並鎖定安全上限** — `requirements.txt` 重新使用 `pip install litellm` 的官方 PyPI 安裝路徑，並在保留歷史最低要求 `>=1.80.10` 的同時增加 `<1.82.7` 的安全上限，避免誤裝已被移除的 `1.82.7` / `1.82.8` 風險版本；Windows 桌面打包指令碼也同步回退到標準 `pip install -r requirements.txt` 鏈路，減少特殊下載分支帶來的維護成本。
- 📨 **Telegram Markdown 解析失敗回退純文字**（fixes #850）— `src/notification_sender/telegram_sender.py` 現在會在 Telegram 返回 `HTTP 400` 且包含 `can't parse entities` / Markdown 解析錯誤時，自動去掉 `parse_mode` 後重試純文字傳送，避免 `*ST` 等正文內容直接導致整條通知失敗。
- 🔢 **A 股同碼實時行情保留交易所提示**（fixes #852）— `DataFetcherManager` 與 `TushareFetcher` 現在會保留 `SZ000001` / `000001.SZ` 這類顯式滬深提示，舊版 Tushare 實時行情降級分支不再把深市 `000001` 誤判成 `sh000001` 上證指數。
- 🎯 **多 Agent 次優買點不再盲目複製理想買點**（fixes #851）— 當多智慧體結果缺少獨立 `secondary_buy` 時，儀表盤現在優先展示 `N/A` 而不是把 fallback 值硬複製成與 `ideal_buy` 完全相同，減少誤導性的雙買點展示。
- 🧩 **Tushare 初始化不再強依賴本地 SDK 包** — `TushareFetcher` 現在直接使用內建 HTTP client 訪問 Tushare Pro，不再在啟動階段先 `import tushare` 才能初始化；修復了 Docker、桌面打包或環境重建後因缺少 `tushare` 包而提前報 `No module named 'tushare'` 的問題，並補充對應迴歸測試。
- ⚙️ **`daily_analysis` 工作流補齊 `DEEPSEEK_API_KEY` 對映** — GitHub Actions 每日分析工作流現在會正確透傳 `DEEPSEEK_API_KEY`，避免雲端任務配置了金鑰卻在執行時拿不到對應環境變數。
- 🖥️ **歷史列表過長股票名稱截斷與懸停展示**（fixes #815）— 歷史列表中過長的股票名稱, 現在會按字元型別自動截斷（英文15/中文8/混合10字元），預設顯示截斷結果，懸停時展示完整名稱；解決 1920x1080 解析度下股票名稱與右側狀態標籤文字重疊的問題。新增 `stockName.ts` 工具函式並補充對應測試。

### 文件

- 🧾 **README 捐贈入口更新為小紅書二維碼** — README 及中英文說明中的贊助入口更新為小紅書二維碼素材，保持展示口徑一致。

## [3.10.1] - 2026-03-24

### 新功能

- 🔔 **Web 端分析推送通知開關**（#808）— 首頁分析按鈕旁新增「推送通知」核取方塊，預設勾選；取消勾選時本次分析不傳送 Telegram/企業微信等推送。API `POST /api/v1/analysis/analyze` 新增 `notify` 欄位（`bool`，預設 `true`），不傳時行為與修改前一致，Bot 和定時任務不受影響。

### 改進

- 🖥️ **問股 / 回測頁面佈局與殼層協同最佳化** — 統一 Chat / Backtest 頁面容器、共享 UI 狀態和跟隨問答互動路徑，移除部分硬編碼高度限制，讓導航框架內的填充與滾動行為更連貫。
- 🎨 **全域性視覺與共享元件繼續收斂** — Light theme 引入動態 HSL 陰影體系，統一側邊欄啟用態、警告元件對比度和聊天氣泡樣式，並把部分零散內聯樣式收口為語義化 CSS 變數，提升一致性與可維護性。

### 修復

- 🖼️ **系統設定智慧匯入檔案選擇恢復** — 修復了“系統設定 > 基礎設定 > 智慧匯入”模組中 “選擇圖片 / 選擇檔案” 兩個按鈕點選無響應的問題。
- 🖥️ **移動端滾動與互動層級修復** — 解決主題切換選單在移動端被主內容遮擋的 z-index 衝突，並恢復首頁長報告場景下的正常縱向滾動，不影響其他頁面現有滾動行為。
- 🧾 **Markdown 純文字複製清洗增強** — 改進純文字匯出演算法，複製分析報告時會更穩定地清除表格分隔符等 Markdown 痕跡，提升分享和歸檔內容的純淨度。
- 🧠 **Trading philosophy injection 覆蓋 legacy + Agent 全鏈路**（#810）— `GeminiAnalyzer`、單 Agent 模式和 skill-aware Prompt 現在共享同一套策略注入狀態；只有隱式回落到內建預設 `bull_trend` 時才保留舊的趨勢型提示，顯式策略選擇或自定義預設 skill 不再被偷偷疊加 `MA5>MA10>MA20` 多頭基線。
- 🛠️ **後端 CI 依賴安裝鏈路穩態化**（#835）— 拆分 backend gate 階段、為依賴安裝增加重試，並把 CI 用的 `litellm` 安裝來源調整為更穩定的 GitHub 源，降低依賴解析抖動導致的 backend gate 偶發失敗。
- 🪟 **Windows 桌面發版構建恢復 LiteLLM 安裝相容性** — `scripts/build-backend.ps1` 現在會先過濾 `requirements.txt` 中的 LiteLLM GitHub 源包，再下載對應 tag 的 zipball 到本地移除上游可選 `enterprise/` 目錄後安裝，繞過 Windows runner 上 Poetry 構建 wheel 時把目錄誤當檔案打包導致的失敗；同時補上 `pip install` 退出碼檢查，避免依賴安裝失敗後只在後續 `python-multipart` 校驗階段才暴露成次生報錯。

### 測試

- 🧪 **問股 / 回測 / 智慧匯入迴歸覆蓋補齊** — 同步更新 E2E 冒煙期望，補充 `DashboardStateBlock`、Chat 頁、智慧匯入檔案選擇與相關互動迴歸斷言，確保近期 UI 調整後的關鍵路徑仍可穩定透過。

## [3.10.0] - 2026-03-24

### 釋出亮點

- 🔎 **自動補全與索引工具擴充套件到三市場** — 補全索引生成鏈路現在同時覆蓋 A 股、港股、美股，配套新增 Tushare 股票列表抓取工具與更完整的靜態索引資料，讓首頁搜尋入口從“能用”走向“更全、更穩”。
- 🖥️ **Dashboard 與報告檢視體驗繼續收口** — 首頁 Dashboard 面板、狀態邊界、字型層級和完整報告表格密度完成一輪統一；報告詳情也補齊了 Markdown/純文字複製與更可靠的按鈕互動，減少歷史報告檢視與分享時的摩擦。
- 🤖 **Agent skill 與市場語義邊界更清晰** — skill bundle、預設策略、回測彙總語義和相容介面進一步收斂；同時分析 Prompt 不再預設寫死 A 股上下文，美股和港股分析也能按各自市場規則生成更貼切的內容。
- ⏰ **定時與桌面配置能力更貼近真實使用場景** — 桌面端支援 `.env` 匯入匯出；`python main.py --schedule --stocks ...` 也不再把啟動時股票快照錯誤帶入後續計劃執行，定時任務會跟隨最新儲存的 `STOCK_LIST`。
### 新功能

- 💾 **桌面端 `.env` 備份/恢復入口**（#754）— 桌面模式下的系統設定頁新增 `匯出 .env` / `匯入 .env` 按鈕，可直接備份當前已儲存配置，或把備份檔案中的鍵值合併恢復到當前桌面端 `.env`；匯入沿用現有 `config_version` 衝突保護與執行時過載鏈路，不改變現有桌面端便攜模式路徑。
- 📊 **Tushare 股票列表獲取工具** — 新增 `scripts/fetch_tushare_stock_list.py`，支援從 Tushare Pro 獲取 A股、港股、美股列表資訊並儲存為 CSV，配有分頁讀取、智慧限流、錯誤處理和進度提示；新增對應使用文件 `docs/TUSHARE_STOCK_LIST_GUIDE.md`。
- 🔎 **索引生成指令碼多市場支援** — `generate_index_from_csv.py` 重構為支援 Tushare 和 AkShare 雙資料來源，同時覆蓋 A股、港股、美股三個市場；新增按市場分類的別名對映（A股、港股常見別名，美股常用股票英文縮寫）；新增 `--source` 引數切換資料來源、`--test` 引數驗證模式；嚴格過濾美股 DUMMY 記錄。
- 🔎 **索引生成指令碼增強** — `generate_stock_index.py` 新增 `--test`/`-t` 測試模式和 `--verbose`/`-v` 詳細輸出模式，新增市場分佈統計，最佳化 JSON 輸出格式。
- 📋 **首頁完整報告支援雙模式複製** — 歷史報告詳情頭部新增“複製 Markdown 原始碼”和“複製純文字”工具按鈕；前者保留原始 Markdown 結構，後者去除常見 Markdown 格式符號，方便分享、歸檔和跨報告比對。複製按鈕文案會跟隨 `REPORT_LANGUAGE` 保持中英文一致，避免英文報告頁出現中文固定文案。
- 🧩 **個股分析頁補齊關聯板塊展示**（#669）— A 股分析寫路徑現在會把 `belong_boards` 一次性寫入 `fundamental_context` / `fundamental_snapshot`，結構化報告詳情同步新增 `belong_boards` 與 `sector_rankings` 欄位，Web 個股分析頁首屏可直接展示所屬板塊及其是否命中當日板塊漲跌榜；無資料時保持 fail-open 隱藏，不影響現有分析主流程。

### 改進

- 🖥️ **Dashboard 面板統一化（PR7-2）** — 新增 `DashboardPanelHeader` 和 `DashboardStateBlock` 作為歷史、報告、資訊、任務和透明度等面板的通用元件；統一了各面板標題層級、載入/空態/錯誤態和 CSS 變數 token。
- 🖥️ **HomePage 狀態邊界收口（PR7-2）** — 引入 `useHomeDashboardState` hook，集中 `stockPoolStore` 狀態選取邏輯，移除 `HomePage` 中重複的本地狀態派生和回撥定義。
- 🧭 **Agent skill 統一到單一配置語義** — Multi-Agent runtime、API、Web chat 和配置後設資料統一圍繞 `skill` 概念收斂；`/api/v1/agent/skills` 成為主發現入口，`AGENT_SKILL_*` 成為主配置面，內建 skill 後設資料也開始宣告預設啟用、排序優先順序、market regime tag 等資訊，減少預設策略散落在程式碼裡的隱式耦合。
- 🔎 **自動補全索引資料更新** — 重新生成 `stocks.index.json`，涵蓋 A股、港股、美股三個市場，提升自動補全覆蓋率。
- 🧾 **Dashboard 字型與完整報告表格密度微調** — 收斂首頁側欄、空狀態、歷史操作區的字型層級，並將完整 Markdown 報告表格 `th/td` 的內邊距調整到更緊湊的 4-6px 區間，讓資訊密度與現有 Dashboard 視覺節奏更一致。

### 修復

- ⏰ **定時模式不再鎖定啟動時 CLI 股票快照** — `python main.py --schedule --stocks ...` 現在不會讓後續計劃執行沿用啟動時的舊股票列表；定時任務每次觸發前都會重新讀取最新儲存的 `STOCK_LIST`，確保 WebUI 或 `.env` 更新後的自選股配置能參與後續推送。
- 🌍 **LLM Prompt 按股票市場動態注入上下文** — 分析鏈路不再把市場規則寫死成 A 股；系統 Prompt 會根據股票程式碼識別 A 股、港股或美股，並注入對應的角色描述與交易規則提示，減少跨市場分析出現口徑錯位或結論失真的問題。
- 🔎 **美股自動補全複用 ticker 去重** — `generate_index_from_csv.py` 在匯入 Tushare `us_basic` CSV 時會先按 `ts_code` 摺疊複用的美股 ticker，優先保留更可能仍在使用的記錄，避免 `stocks.index.json` 出現重複 `canonicalCode` 後讓 Web 自動補全展示歷史名稱或提交歧義程式碼。
- 🧾 **Web 報告詳情複製互動穩定性修復**（#749）— `ReportDetails` 中“原始分析結果 / 分析快照”的複製按鈕補齊可點選層級，避免被下方 JSON 內容覆蓋；兩個面板的複製提示也改為各自獨立，不再出現複製一個後兩個按鈕同時顯示“已複製”的誤導反饋。
- 📊 **Agent skill 回測與相容介面語義收斂** — `get_skill_backtest_summary` 現在要求顯式傳入 `skill_id`，缺失時返回明確校驗提示；倉庫尚未持久化真實 skill 級彙總時會返回明確的 unsupported/info 響應，並保留 `normalized` 與 `*_pct` 相容欄位，避免沿用 overall 指標誤導 Agent 或使用者。
- 🔧 **Skill 預設選擇與相容層行為加固** — `allowed-tools` 會繼續僅作為 `SKILL.md` bundle 後設資料保留，不再洩露到執行時工具選擇；`/api/v1/agent/strategies` 恢復舊 payload 形狀；顯式傳入 `skills: []` 時會清空陳舊上下文；當使用者明確選擇策略 skill 時不再偷偷疊加預設 bull-trend，而在 `AGENT_SKILLS` 為空時則統一隻回落到單一主預設 skill。

### 測試

- 🧪 **Dashboard 元件測試覆蓋率擴充套件（PR7-2）** — 新增 `ReportNews` 和 `TaskPanel` 測試；對 `HistoryList`、`ReportDetails`、`HomePage`、`useDashboardLifecycle` 和 `stockPoolStore` 增強了斷言覆蓋，包括刪除回退、移動端抽屜和任務生命週期等場景。
- 🧪 **多市場索引生成測試補齊** — 新增 `tests/test_generate_index_from_csv.py`，覆蓋 Tushare/AkShare 雙資料來源解析、多市場判斷、美股 DUMMY 過濾與重複 ticker 去重等核心路徑。
- 🧪 **關聯板塊寫入與 API 契約迴歸** — 新增 `tests/test_pipeline_related_boards.py`，並補充分析歷史與分析介面契約測試，確保 `belong_boards` / `sector_rankings` 只做增量擴充套件且保持 fail-open。
- 🧪 **定時模式股票列表語義迴歸測試** — 新增 `tests/test_main_schedule_mode.py`，覆蓋定時模式忽略啟動時 `--stocks` 快照、單次執行仍保留 CLI 股票覆蓋的邊界場景。

### 文件

- 📘 **新增 Tushare 股票列表工具文件** — 新增 `docs/TUSHARE_STOCK_LIST_GUIDE.md`，說明股票列表抓取工具的使用方法、資料格式和常見問題。
- 🌍 **補齊定時模式與關聯板塊的雙語說明** — `docs/full-guide.md` / `docs/full-guide_EN.md` 現在明確說明 scheduled mode 會在每次執行前重新讀取 `STOCK_LIST`，並同步補充個股關聯板塊展示能力說明，減少配置預期偏差。
- 🧭 **調整 Agent 術語相容文案** — README、雙語文件、設定頁與問股介面繼續以“策略”作為使用者入口主稱呼，同時補充 `skill` 作為內部統一命名，降低遷移期理解成本。

## [3.9.0] - 2026-03-20

### 釋出亮點

- 🤖 **模型鏈路與報告語言更靈活** — Agent 現在可以透過 `AGENT_LITELLM_MODEL` 獨立選擇模型鏈路，普通分析與 Agent 報告也可透過 `REPORT_LANGUAGE=zh|en` 輸出統一語言，減少“英文內容 + 中文殼子”這類混排問題，並允許團隊分別權衡主分析與 Agent 的成本、速度和能力。
- 🔎 **首頁分析體驗完成一輪閉環最佳化** — 首頁新增 A 股自動補全，支援程式碼、中文名、拼音和別名檢索；同時 Dashboard 狀態收口到統一 store，歷史、報告、新聞與 Markdown 抽屜的互動更穩定，“Ask AI” 追問也會優先攜帶當前報告上下文。
- 💬 **通知與檢索能力繼續外擴** — 新增 Slack 一等通知通道；SearXNG 在未配置自建例項時可以自動發現公共例項並按受控輪詢降級；Tavily 時效新聞鏈路修復後，嚴格時效過濾不再錯誤丟光有效結果。
- 💼 **持股與市場覆盤鏈路更穩** — A 股 market review 可選接入 TickFlow 強化指數與漲跌統計；持股賬本寫入改為序列化以縮小併發超賣視窗；匯率重新整理入口和禁用態提示也更加清晰，減少使用者誤判。

### 新功能

- 🔎 **Web 股票自動補全 MVP** — 首頁分析輸入框新增本地索引驅動的自動補全，支援股票程式碼、中文名、拼音和別名匹配；選中候選後會提交 canonical code，並透傳 `stock_name`、`original_query`、`selection_source` 到分析請求、任務狀態和 SSE 事件；索引載入失敗時自動退回舊輸入模式，不阻斷原有提交流程。同步補充了靜態索引載入器、索引生成指令碼和前後端契約測試。分階段進行開發，第一階段僅支援 A 股。
- 💬 **Slack 一等通知通道** — 新增 Slack 原生通知支援，同時支援 Bot Token 和 Incoming Webhook 兩種接入方式；同時配置時優先使用 Bot API，確保文字與圖片傳送到同一頻道；Bot Token 模式支援圖片上傳（raw body POST，不使用 multipart）；新增 `SLACK_BOT_TOKEN`、`SLACK_CHANNEL_ID`、`SLACK_WEBHOOK_URL` 配置項，GitHub Actions 工作流同步補齊對應 Secrets 傳遞。
- 🌍 **報告輸出語言可配置**（Issue #758）— 新增 `REPORT_LANGUAGE=zh|en`，預設 `zh`；語言設定會同步注入普通分析與 Agent Prompt，並覆蓋 Markdown/Jinja 模板、通知 fallback、歷史/API `report_language` 後設資料及 Web 報告頁固定文案，避免“英文內容 + 中文殼子”的混合輸出。
- 🚀 **Agent 與普通分析模型解耦**（Issue #692）— 新增 `AGENT_LITELLM_MODEL`（留空繼承 `LITELLM_MODEL`，無字首按 `openai/<model>` 歸一）；Agent 執行鏈路與 `/api/v1/agent/models` 的 `is_primary/is_fallback` 標記改為基於 Agent 實際模型鏈路；系統配置與啟動期校驗補齊 `AGENT_LITELLM_MODEL` 的 `unknown_model/missing_runtime_source` 檢查；Web 設定頁新增 Agent 主模型選擇並與通道模式執行時配置同步。
- 🔎 **SearXNG 公共例項自動發現與受控輪詢**（#752）— 新增 `SEARXNG_PUBLIC_INSTANCES_ENABLED`，在未配置 `SEARXNG_BASE_URLS` 時預設從 `searx.space` 拉取公共例項列表，並按受控輪詢順序選擇例項；同次請求內遇到超時、連線錯誤、HTTP 非 200 或無效 JSON 會自動切換到下一個例項。已配置自建例項的使用者保持原有優先順序與語義不變；`daily_analysis` GitHub Actions 工作流也已支援顯式透傳該開關並在啟動日誌中展示當前狀態。
- 📈 **TickFlow market review enhancement** (#632) — 新增可選 `TICKFLOW_API_KEY`；配置後，A 股大盤覆盤的主要指數行情優先嚐試 TickFlow；若當前 TickFlow 套餐支援標的池查詢，市場漲跌統計也會優先嚐試 TickFlow。失敗或許可權不足時立即回退到現有 `AkShare / Tushare / efinance` 鏈路；板塊漲跌榜回退順序保持不變。接入層同時適配了真實 SDK 契約：主指數查詢按單次請求上限分批拉取，並將 TickFlow 返回的比例型 `change_pct` / `amplitude` 統一轉換為專案內部的百分比口徑。

### 改進

- **Dashboard state slice and workspace closure** — moved Home / Dashboard state into `stockPoolStore`, consolidated history selection, report loading, task syncing, polling refresh, and markdown drawer handling under a single state slice.
- **Dashboard panel standardization** — kept the current dashboard layout contract stable while unifying history, report, news, and markdown presentation with shared tokens, standardized states, and bounded in-panel scrolling for the history list.
- **Dashboard-to-chat follow-up bridge** — routed “Ask AI” follow-ups through report-context hydration instead of direct cross-page state coupling, while keeping chat sends usable when enriched history context is still loading.
- 💼 **持股賬本併發寫入序列化**（#742）— 持股源事件寫入/刪除現在會在 SQLite 下先獲取序列化寫鎖，減少併發賣出把超售流水寫入賬本的視窗；直接持股寫介面在鎖競爭時返回 `409 portfolio_busy`，CSV 匯入保持逐條提交併把 busy 計入 `failed_count`。
- 💱 **持股頁匯率手動重新整理入口補齊**（#748）— Web `/portfolio` 頁面現在會在“匯率狀態”卡片中展示“重新整理匯率”按鈕，直接呼叫現有 `POST /api/v1/portfolio/fx/refresh` 介面；重新整理後會僅過載快照與風險資料，並以內聯摘要反饋“已更新 / 仍 stale / 重新整理失敗”的結果，減少使用者對 `fxStale` 長時間停留的誤解。

### 修復

- 🔎 **Web 自動補全 Enter 提交語義修正** — 股票自動補全在搜尋命中候選時不再預設高亮第一項；候選列表展開但使用者尚未用方向鍵或滑鼠明確選中時，按 Enter 會繼續提交原始輸入，避免手動輸入被第一條候選靜默覆蓋。
- 🌍 **補齊 `REPORT_LANGUAGE` 啟動解析與歷史展示本地化邊界** — `Config` 在啟動時繼續遵循“真實環境變數優先、`.env` 兜底”的既有語義，並在兩者衝突時輸出顯式警告，減少 `REPORT_LANGUAGE` 來源不清帶來的誤判；同時 `/api/v1/history/{id}` 英文詳情響應會同步本地化 `sentiment_label`，歷史 Markdown 也會正確識別英文 `bias_status` 的風險等級 emoji，避免出現 `樂觀` 或 `🚨Safe` 這類中英混排/誤報展示。
- 📰 **Tavily 時效新聞檢索釋出時間對映修復**（#782）— Tavily 在股票新聞和嚴格時效的情報維度中現在會顯式使用 `topic="news"`，併相容 `published_date` / `publishedDate` 兩種釋出時間欄位；修復了 Tavily 明明返回結果卻在後續硬過濾階段被全部記為 `drop_unknown` 丟棄的問題，同時將機構分析、業績預期、行業分析等分析型維度恢復為寬源搜尋，不再被統一壓縮成新聞模式。
- 💱 **持股頁匯率重新整理禁用語義修正**（#772）— 當 `PORTFOLIO_FX_UPDATE_ENABLED=false` 時，`POST /api/v1/portfolio/fx/refresh` 現在會返回顯式 `refresh_enabled=false` 與 `disabled_reason`，Web `/portfolio` 頁面會明確提示“匯率線上重新整理已被禁用”，不再誤報“當前範圍無可重新整理的匯率對”。
- 🤖 **Agent timeout and config hardening** — `AGENT_ORCHESTRATOR_TIMEOUT_S` now also protects the legacy single-agent ReAct loop, parallel tool batches stop waiting once the remaining budget is exhausted, and invalid numeric `.env` values fall back to safe defaults with warnings instead of crashing startup.
- 🌐 **CORS wildcard + credentials compatibility** — `CORS_ALLOW_ALL=true` no longer combines `allow_origins=["*"]` with credentialed requests, avoiding browser-side cross-origin failures in demo/development setups.
- 🧭 **Unavailable Agent settings hidden from Web UI** — Deep Research / Event Monitor controls are now treated as compatibility-only metadata in the current branch and are removed from the Settings page to avoid exposing non-functional toggles.

### 文件

- 新增 Ollama 本地模型配置說明，同步更新 `README.md` 與 `docs/README_EN.md`（Fixes #690）
- 完善 Ollama 配置說明：`docs/full-guide.md` / `docs/full-guide_EN.md` 環境變數表與 Note 補充 `OLLAMA_API_BASE`，避免英文使用者誤以為 Ollama 不能作為獨立配置入口；合併重複的 `OLLAMA_API_BASE` 條目為單一條目
- 明確文件同步治理邊界：補充 `README.md`、專題文件、雙語文件與交付說明之間的預設同步規則，減少後續文件漂移

## [3.8.0] - 2026-03-17

### 釋出亮點

- 🎨 **Web 介面完成一輪骨架升級** — 新的 App Shell、側邊導航、主題能力、登入與系統設定流程已經串成統一體驗，桌面端載入背景也完成對齊。
- 📈 **分析上下文繼續補強** — 美股新增社交輿情情報，A 股補齊財報與分紅結構化上下文，Tushare 新接入籌碼分佈和行業板塊漲跌資料。
- 🔒 **執行穩定性與配置相容性提升** — 退出登入會立即讓舊會話失效，定時啟動相容舊配置，執行中的 `MAX_WORKERS` 調整和新聞時效視窗反饋更清晰。
- 💼 **持股糾錯鏈路更完整** — 超售會被前置攔截，錯誤交易/資金流水/公司行為可以直接刪除回滾，便於修復髒資料。

### 新功能

- 📱 **美股社交輿情情報** — 新增 Reddit / X / Polymarket 社交媒體情緒資料來源，為美股分析提供實時社交熱度、情緒評分和提及量等補充指標；完全可選，僅在配置 `SOCIAL_SENTIMENT_API_KEY` 後對美股生效。
- 📊 **A 股財報與分紅結構化增強**（Issue #710）— `fundamental_context.earnings.data` 新增 `financial_report` 與 `dividend` 欄位；分紅統一按“僅現金分紅、稅前口徑”計算，並補充 `ttm_cash_dividend_per_share` 與 `ttm_dividend_yield_pct`；分析/歷史 API 的 `details` 追加 `financial_report`、`dividend_metrics` 可選欄位，保持 fail-open 與向後相容。
- 🔍 **接入 Tushare 籌碼與行業板塊介面** — 新增籌碼分佈、行業板塊漲跌資料獲取能力，並統一納入配置化資料來源優先順序；預設按上海時間區分盤中/盤後交易日取數，優先使用 Tushare 同花順介面，必要時降級到東財。
- 🧱 **Web UI 基礎骨架升級** — 重建共享設計令牌與通用元件，新增 App Shell、Theme Provider、側邊導航，並同步調整 Electron 載入背景，為 Web / Desktop 的統一體驗打底。
- 🔐 **登入與系統設定流程重做** — 重構 Login、Settings 與 Auth 管理流程，補上顯式的認證 setup-state 處理，並讓 Web 端與執行時認證配置 API 行為對齊。
- 🧪 **前端迴歸與冒煙覆蓋補強** — 新增並擴充套件登入、首頁、聊天、移動端 Shell、設定頁、回測入口等關鍵路徑的元件測試與 Playwright smoke coverage。

### 變更

- 🧭 **頁面接入新 Shell 佈局契約** — Home、Chat、Settings、Backtest 已統一接入新的頁面容器、抽屜和滾動約定，降低 UI 遷移期間的頁面行為不一致。
- 💾 **設定頁狀態同步更穩** — 最佳化草稿保留、直接儲存同步與衝突處理，減少模組級儲存後前後端配置狀態不一致的問題。
- 🎭 **登入頁視覺基線迴歸** — 登入頁恢復到既有 `006` 分支的視覺基線，同時保留新的認證狀態邏輯和統一表單互動模型。
- 🏛️ **AI 協作治理資產加固** — 收斂並加強 `AGENTS.md`、`CLAUDE.md`、Copilot 指令和校驗指令碼的一致性約束，降低治理資產長期漂移風險。

### Added

- **Web UI foundation refresh** — rebuilt shared design tokens and common primitives, introduced the app shell, theme provider, sidebar navigation, and Electron loading background alignment for the upgraded desktop/web experience
- **Settings and auth workflow overhaul** — rebuilt the Login, Settings, and Auth management flows, added explicit auth setup-state handling, and aligned the Web UI with the runtime auth configuration APIs
- **UI regression coverage and smoke checks** — expanded targeted frontend tests and added Playwright smoke coverage for login, home, chat, mobile shell, settings, and backtest entry flows

### Changed

- **Shell-driven page integration** — aligned Home, Chat, Settings, and Backtest with the new shell layout contract so routing, drawer behavior, and page-level scrolling are consistent during the UI migration
- **Settings state consistency** — refined draft preservation, direct-save synchronization, and conflict handling so module-level saves no longer leave the page out of sync with backend config state
- **Login visual baseline** — restored the login page visual treatment to the established `006` branch baseline while keeping the newer auth-state logic and unified form interaction model

### 修復

- ⏰ **定時啟動立即執行相容舊配置**（Issue #726）— `SCHEDULE_RUN_IMMEDIATELY` 未設定時會回退讀取 `RUN_IMMEDIATELY`，修復升級後舊 `.env` 在定時模式下的相容性問題；同時澄清 `.env.example` / README 中兩個配置項的適用範圍，並註明 Outlook / Exchange 強制 OAuth2 暫不支援。
- 🧵 **執行期 `MAX_WORKERS` 配置生效與可解釋性增強**（#633）— 修復非同步分析佇列未按 `MAX_WORKERS` 同步的問題；新增任務佇列併發 in-place 同步機制（空閒即時生效、繁忙延後），並在設定儲存反饋與執行日誌中明確輸出 `profile/max/effective`，減少“引數未生效”誤解。
- 🔐 **退出登入立即失效現有會話** — `POST /api/v1/auth/logout` 現在會輪換 session secret，避免舊 cookie 在退出後仍可繼續訪問受保護介面；同瀏覽器標籤頁和併發頁面會被同步登出。認證開啟時，該介面也不再屬於匿名白名單，未登入請求會返回 `401`，避免匿名請求觸發全域性 session 失效。
- 🧮 **Tushare 板塊/籌碼呼叫限流與跨日快取修復** — 新增的 `trade_cal`、行業板塊排行、籌碼分佈鏈路統一接入 `_check_rate_limit()`；交易日曆快取改為按自然日重新整理，避免服務跨天執行後繼續沿用舊交易日判斷取數日期。
- 💼 **持股超售攔截與錯誤流水恢復**（#718）— `POST /api/v1/portfolio/trades` 現在會在寫入前校驗可賣數量，超售返回 `409 portfolio_oversell`；持股頁新增交易 / 資金流水 / 公司行為刪除能力，刪除後會同步失效部位快取與未來快照，便於從錯誤流水中直接恢復。
- 📧 **郵件中文發件人名編碼**（#708）— 郵件通知現在會對包含中文的 `EMAIL_SENDER_NAME` 自動做 RFC 2047 編碼，並在異常路徑補充 SMTP 連線清理，修復 GitHub Actions / QQ SMTP 下 `'ascii' codec can't encode characters` 導致的傳送失敗。
- 🐛 **港股 Agent 實時行情去重與快速路由** — 統一 `HK01810` / `1810.HK` / `01810` 等港股程式碼歸一規則；港股實時行情改為直接走單次 `akshare_hk` 路徑，避免按 A 股 source priority 重複觸發同一失敗介面；Agent 執行期對顯式 `retriable=false` 的工具失敗增加短路快取，減少同輪分析中的重複失敗呼叫。
- 📰 **新聞時效硬過濾與策略分窗**（#697）— 新增 `NEWS_STRATEGY_PROFILE`（`ultra_short/short/medium/long`）並與 `NEWS_MAX_AGE_DAYS` 統一計算有效視窗；搜尋結果在返回後執行釋出時間硬過濾（時間未知剔除、超窗剔除、未來僅容忍 1 天），並在歷史 fallback 鏈路追加相同約束，避免舊聞再次進入“最新動態/風險警報”。

### 文件

- ☁️ **新增雲伺服器 Web 介面部署與訪問教程**（Fixes #686）— 補充從雲端部署到外部訪問的落地說明，降低遠端自託管門檻。
- 🌍 **補齊英文文件索引與協作文件** — 新增英文文件索引、貢獻指南、Bot 命令文件，並補充中英雙語 issue / PR 模板，方便中英文協作與外部貢獻者理解專案入口。
- 🏷️ **本地化 README 補充 Trendshift badge** — 在多語言 README 中同步補上新版能力入口標識，減少中英文說明面不一致。

## [3.7.0] - 2026-03-15

### 新功能

- 💼 **持股管理 P0 全功能上線**（#677，對應 Issue #627）
  - **核心賬本與快照閉環**：新增帳戶、交易、現金流水、企業行為、持股快取、每日快照等核心資料模型與 API 端點；支援 FIFO / AVG 雙成本法回放；同日事件順序固定為 `現金 → 企業行為 → 交易`；持股快照寫入採用原子事務。
  - **券商 CSV 匯入**：支援華泰 / 中信 / 招商首批適配，含列名別名相容；兩階段介面（解析預覽 + 確認提交）；`trade_uid` 優先、key-field hash 兜底的冪等去重；前導零股票程式碼完整保留。
  - **組合風險報告**：集中度風險（Top Positions + A 股板塊口徑）、歷史回撤監控（支援回填缺失快照）、止損接近預警；多幣種統一換算 CNY 口徑；汲取失敗時回退最近成功匯率並標記 stale。
  - **Web 持股頁**（`/portfolio`）：組合總覽、持股明細、集中度餅圖、風險摘要、全組合 / 單帳戶切換；手工錄入交易 / 資金流水 / 企業行為；內嵌帳戶建立入口；CSV 解析 + 提交閉環與券商選擇器。
  - **Agent 持股工具**：新增 `get_portfolio_snapshot` 資料工具，預設緊湊摘要，可選持股明細與風險資料。
  - **事件查詢 API**：新增 `GET /portfolio/trades`、`GET /portfolio/cash-ledger`、`GET /portfolio/corporate-actions`，支援日期過濾與分頁。
  - **可擴充套件 Parser Registry**：應用級共享註冊，支援執行時註冊新券商；新增 `GET /portfolio/imports/csv/brokers` 發現介面。

- 🎨 **前端設計系統與原子元件庫**（#662）
  - 引入漸進式雙主題架構（HSL 變數化設計令牌），清理歷史 Legacy CSS；重構 Button / Card / Badge / Collapsible / Input / Select 等 20+ 核心元件；新增 `clsx` + `tailwind-merge` 類名合併工具；提升歷史記錄、LLM 配置等頁面可讀性。

- ⚡ **分析 API 非同步契約與啟動最佳化**（#656）
  - 規範 `POST /api/v1/analysis/analyze` 非同步請求的返回契約；最佳化服務啟動輔助邏輯；修復前端報告型別聯合定義與後端響應對齊問題。

### 修復

- 🔔 **Discord 環境變數向後相容**（#659）：執行時新增 `DISCORD_CHANNEL_ID` → `DISCORD_MAIN_CHANNEL_ID` 的 fallback 讀取；歷史配置使用者無需修改即可恢復 Discord Bot 通知；全部相關文件與 `.env.example` 對齊。
- 🔧 **GitHub Actions Node 24 升級**（#665）：將所有 GitHub 官方 actions 升級至 Node 24 相容版本，消除 CI 日誌中的 Node.js 20 deprecation warning（影響 2026-06-02 強制升級視窗）。
- 📅 **持股頁預設日期本地化**：手工錄入表單預設日期改用本地時間（`getFullYear/Month/Date`），修復 UTC-N 時區使用者在當天晚間出現日期偏移的問題。
- 🔁 **CSV 匯入去重邏輯加固**：dedup hash 納入行序號作為區分因子，確保同欄位合法分筆成交不被誤摺疊；同時在 `trade_uid` 存在時也持久化 hash，防止混合來源重複寫入。

### 變更

- `POST /api/v1/portfolio/trades` 在同帳戶內 `trade_uid` 衝突時返回 `409`。
- 持股風險響應新增 `sector_concentration` 欄位（增量擴充套件），原有 `concentration` 欄位保持不變。
- 分析 API `analyze` 介面非同步行為契約文件化；前端報告型別聯合更新。

### 測試

- 新增持股核心服務測試（FIFO / AVG 部分賣出、同日事件順序、重複 `trade_uid` 返回 409、快照 API 契約）。
- 新增 CSV 匯入冪等性、合法分筆成交不誤去重、去重邊界、風險閾值邊界、匯率降級行為測試。
- 新增 Agent `get_portfolio_snapshot` 工具呼叫測試。
- 新增分析 API 非同步契約迴歸測試。

## [3.6.0] - 2026-03-14

### Added
- 📊 **Web UI Design System** — implemented dual-theme architecture and terminal-inspired atomic UI components
- 📊 **UI Components Refactoring** — integrated `clsx` and `tailwind-merge` for robust class composition across Web UI

- 🗑️ **History batch deletion** — Web UI now supports multi-selection and batch deletion of analysis history; added `POST /api/v1/history/batch-delete` endpoint and `ConfirmDialog` component.
- 🔐 **Auth settings API** — new `POST /api/v1/auth/settings` endpoint to enable or disable Web authentication at runtime and set the initial admin password when needed
- openclaw Skill 整合指南 — 新增 [docs/openclaw-skill-integration.md](openclaw-skill-integration.md)，說明如何透過 openclaw Skill 呼叫 DSA API
- ⚙️ **LLM channel protocol/test UX** — `.env` and Web settings now share the same channel shape (`LLM_CHANNELS` + `LLM_<NAME>_PROTOCOL/BASE_URL/API_KEY/MODELS/ENABLED`); settings page adds per-channel connection testing, primary/fallback/vision model selection, and protocol-aware model prefixing
- 🤖 **Agent architecture Phase 0+1** — shared protocols (`AgentContext`, `AgentOpinion`, `StageResult`), extracted `run_agent_loop()` runner, `AGENT_ARCH` switch (`single`/`multi`), config registry entries
- 🔍 **Bot NL routing** — two-layer natural-language routing: cheap regex pre-filter (stock codes + finance keywords) → lightweight LLM intent parsing; controlled by `AGENT_NL_ROUTING=true`; supports multi-stock and strategy extraction
- 💬 **`/ask` multi-stock analysis** — comma or `vs` separated codes (max 5), parallel thread execution with 150s timeout (preserves partial results), Markdown comparison summary table at top
- 📋 **`/history` command** — per-user session isolation via `{platform}_{user_id}:{scope}` format (colon delimiter prevents prefix collision); lists both `/chat` and `/ask` sessions; view detail or clear
- 📊 **`/strategies` command** — lists available strategy YAML files grouped by category (趨勢/形態/反轉/框架) with ✅/⬜ activation status
- 🔧 **Backtest summary tools** — `get_strategy_backtest_summary` and `get_stock_backtest_summary` registered as read-only Agent tools
- ⚙️ **Agent auto-detection** — `is_agent_available()` auto-detects from `LITELLM_MODEL`; explicit `AGENT_MODE=true/false` takes full precedence
- 🏗️ **Multi-Agent orchestrator (Phase 2)** — `AgentOrchestrator` with 4 modes (`quick`/`standard`/`full`/`strategy`); drop-in replacement for `AgentExecutor` via `AGENT_ARCH=multi`; `BaseAgent` ABC with tool subset filtering, cached data injection, and structured `AgentOpinion` output
- 🧩 **Specialised agents (Phase 2-4)** — `TechnicalAgent` (8 tools, trend/MA/MACD/volume/pattern analysis), `IntelAgent` (news & sentiment, risk flag propagation), `DecisionAgent` (synthesis into Decision Dashboard JSON), `RiskAgent` (7 risk categories, two-level severity with soft/hard override)
- 📈 **Strategy system (Phase 3)** — `StrategyAgent` (per-strategy evaluation from YAML skills), `StrategyRouter` (rule-based regime detection → strategy selection), `StrategyAggregator` (weighted consensus with backtest performance factor)
- 🔬 **Deep Research agent (Phase 5)** — `ResearchAgent` with 3-phase approach (decompose → research sub-questions → synthesise report); token budget tracking; new `/research` bot command with aliases (`/深研`, `/deepsearch`)
- 🧠 **Memory & calibration (Phase 6)** — `AgentMemory` with prediction accuracy tracking, confidence calibration (activates after minimum sample threshold), strategy auto-weighting based on historical win rate
- 📊 **Portfolio Agent (Phase 7)** — `PortfolioAgent` for multi-stock portfolio analysis (position sizing, sector concentration, correlation risk, cross-market linkage, rebalance suggestions)
- 🔔 **Event-driven alerts (Phase 7)** — `EventMonitor` with `PriceAlert`, `VolumeAlert`, `SentimentAlert` rules; async checking, callback notifications, serializable persistence
- ⚙️ **New config entries** — `AGENT_ORCHESTRATOR_MODE`, `AGENT_RISK_OVERRIDE`, `AGENT_DEEP_RESEARCH_BUDGET`, `AGENT_MEMORY_ENABLED`, `AGENT_STRATEGY_AUTOWEIGHT`, `AGENT_STRATEGY_ROUTING` — all registered in `config.py` + `config_registry.py` (WebUI-configurable)

### Changed
- 🔐 **Auth password state semantics** — stored password existence is now tracked independently from auth enablement; when auth is disabled, `/api/v1/auth/status` returns `passwordSet=false` while preserving the saved password for future re-enable
- 🔐 **Auth settings re-enable hardening** — re-enabling auth with a stored password now requires `currentPassword`, and failed session creation rolls back the auth toggle to avoid lockout
- ♻️ **AgentExecutor refactored** — `_run_loop` delegates to shared `runner.run_agent_loop()`; removed duplicated serialization/parsing/thinking-label code
- ♻️ **Unified agent switch** — Bot, API, and Pipeline all use `config.is_agent_available()` instead of divergent `config.agent_mode` checks
- 📖 **README.md** — expanded Bot commands section (ask/chat/strategies/history), added NL routing note, updated agent mode description
- 📖 **.env.example** — added `AGENT_ARCH` and `AGENT_NL_ROUTING` configuration documentation
- 🔌 **Analysis API async contract** — `POST /api/v1/analysis/analyze` now documents distinct async `202` payloads for single-stock vs batch requests, and `report_type=full` is treated consistently with the existing full-report behavior

### Fixed
- 🐛 **Analysis API blank-code guardrails** — `POST /api/v1/analysis/analyze` now drops whitespace-only entries before batch enqueue and returns `400` when no valid stock code remains
- 🐛 **Bare `/api` SPA fallback** — unknown API paths now return JSON `404` consistently for both `/api/...` and the exact `/api` path
- 🎮 **Discord channel env compatibility** — runtime now accepts legacy `DISCORD_CHANNEL_ID` as a fallback for `DISCORD_MAIN_CHANNEL_ID`, and the docs/examples now use the same variable name as the actual workflow/config implementation
- 🐛 **Session secret rotation on Windows** — use atomic replace so auth toggles invalidate existing sessions even when `.session_secret` already exists
- 🐛 **Auth toggle atomicity** — persist `ADMIN_AUTH_ENABLED` before rotating session secret; on rotation failure, roll back to the previous auth state
- 🔧 **LLM runtime selection guardrails** — YAML 模式下通道編輯器不再覆蓋 `LITELLM_MODEL` / fallback / Vision；系統配置校驗補上全部通道禁用後的執行時來源檢查，並修復 `vertexai/...` 這類協議別名模型被重複加字首的問題
- 🐛 **Multi-stock `/ask` follow-up regressions** — portfolio overlay now shares the same timeout budget as the per-stock phase and is skipped on timeout instead of blocking the bot reply; `/history` now stores the readable per-stock summary instead of raw dashboard JSON; condensed multi-stock output now renders numeric `sniper_points` values
- 🐛 **Decision dashboard enum compatibility** — multi-agent `DecisionAgent` now keeps `decision_type` within the legacy `buy|hold|sell` contract and normalizes stray `strong_*` outputs before risk override, pipeline conversion, and downstream統計/通知彙總
- 🛟 **Multi-Agent partial-result fallback** — `IntelAgent` now caches parsed intel for downstream reuse, shared JSON parsing tolerates lightly malformed model output, and the orchestrator preserves/synthesizes a minimal dashboard on timeout or mid-pipeline parse failure instead of always collapsing to `50/觀望/未知`
- 🐛 **Shared LiteLLM routing restored** — bot NL intent parsing and `ResearchAgent` planning/synthesis now reuse the same LiteLLM adapter / Router / fallback / `api_base` injection path as the main Agent flow, so `LLM_CHANNELS` / `LITELLM_CONFIG` / OpenAI-compatible deployments behave consistently
- 🐛 **Bot chat session backward compatibility** — `/chat` now keeps using the legacy `{platform}_{user_id}` session id when old history already exists, and `/history` can still list / view / clear those pre-migration sessions alongside the new `{platform}_{user_id}:chat` format
- 🐛 **EventMonitor unsupported rule rejection** — config validation/runtime loading now reject or skip alert types the monitor cannot actually evaluate yet, so schedule mode no longer silently accepts permanent no-op rules
- 🐛 **P0 基本面聚合穩定性修復** (#614) — 修復 `get_stock_info` 板塊語義迴歸（新增 `belong_boards` 並保留 `boards` 相容別名）、引入基本面上下文精簡返回以控制 token、為基本面快取增加最大條目淘汰，並補齊 ETF 總體狀態聚合與 NaN 板塊欄位過濾，保證 fail-open 與最小入侵。
- 🔧 **GitHub Actions 搜尋引擎環境變數補充** — 工作流新增 `MINIMAX_API_KEYS`、`BRAVE_API_KEYS`、`SEARXNG_BASE_URLS` 環境變數對映，使 GitHub Actions 使用者可配置 MiniMax、Brave、SearXNG 搜尋服務（此前 v3.5.0 已新增 provider 實現但缺少工作流配置）
- 🤖 **Multi-Agent runtime consistency** — `AGENT_MAX_STEPS` now propagates to each orchestrated sub-agent; added cooperative `AGENT_ORCHESTRATOR_TIMEOUT_S` budget to stop overlong pipelines before they cascade further
- 🔌 **Multi-Agent feature wiring** — `AGENT_RISK_OVERRIDE` now actively downgrades final dashboards on hard risk findings; `AGENT_MEMORY_ENABLED` now injects recent analysis memory + confidence calibration into specialised agents; multi-stock `/ask` now runs `PortfolioAgent` to add portfolio-level allocation and concentration guidance
- 🔔 **EventMonitor runtime wiring** — schedule mode can now load alert rules from `AGENT_EVENT_ALERT_RULES_JSON`, poll them at `AGENT_EVENT_MONITOR_INTERVAL_MINUTES`, and send triggered alerts through the existing notification service
- 🛠️ **Follow-up stability fixes** — multi-stock `/ask` now falls back to usable text output when dashboard JSON parsing fails; EventMonitor skips semantically invalid rules instead of aborting schedule startup; background alert polling now runs independently of the main scheduled analysis loop
- 🧪 **Multi-Agent regression coverage** — added orchestrator execution tests for `run()`, `chat()`, critical-stage failure, graceful degradation, and timeout handling
- 🧹 **PortfolioAgent cleanup** — `post_process()` now reuses shared JSON parsing and removed stale unused imports
- 🚦 **Bot async dispatch** — `CommandDispatcher` now exposes `dispatch_async()`; NL intent parsing and default command execution are offloaded from the event loop, DingTalk stream awaits async handlers directly, and Feishu stream processing is moved off the SDK callback thread
- 🌐 **Async webhook handler** — new `handle_webhook_async()` function in `bot/handler.py` for use from async contexts (e.g. FastAPI); calls `dispatch_async()` directly without thread bridging
- 🧵 **Feishu stream ThreadPoolExecutor** — replaced unbounded per-message `Thread` spawning with a capped `ThreadPoolExecutor(max_workers=8)` to prevent thread explosion under message bursts
- 🔒 **EventMonitor safety** — `_check_volume()` now safely handles `get_daily_data` returning `None` (no tuple-unpacking crash); `on_trigger` callbacks support both sync and async callables via `asyncio.to_thread`/`await`
- 🧹 **ResearchAgent dedup** — `_filtered_registry()` now delegates to `BaseAgent._filtered_registry()` instead of duplicating the filtering logic
- 🧹 **Bot trailing whitespace cleanup** — removed W291/W293 whitespace issues across `bot/handler.py`, `bot/dispatcher.py`, `bot/commands/base.py`, `bot/platforms/feishu_stream.py`, `bot/platforms/dingtalk_stream.py`
- 🐛 **Dispatcher `_parse_intent_via_llm` safety** — replaced fragile `'raw' in dir()` with `'raw' in locals()` for undefined-variable guard in `JSONDecodeError` handler
- 🐛 **籌碼結構 LLM 未填寫時兜底補全** (#589) — DeepSeek 等模型未正確填寫 `chip_structure` 時，自動用資料來源已獲取的籌碼資料補全，保證各模型展示一致；普通分析與 Agent 模式均生效
- 🐛 **歷史報告狙擊點位顯示原始文字** (#452) — 歷史詳情頁現優先展示 `raw_result.dashboard.battle_plan.sniper_points` 中的原始字串，避免 `analysis_history` 數值列把區間、說明文字或複雜點位壓縮成單個數字；保留原有數值列作為回退
- 🐛 **Session prefix collision** — user ID `123` could see sessions of user `1234` via `startswith`; fixed with colon delimiter in session_id format
- 🐛 **NL pre-filter false positives** — `re.IGNORECASE` caused `[A-Z]{2,5}` to match common English words like "hello"; removed global flag, use inline `(?i:...)` only for English finance keywords
- 🐛 **Dotted ticker in strategy args** — `_get_strategy_args()` didn't recognize `BRK.B` as a stock code, leaving it in strategy text; now accepts `TICKER.CLASS` format
- ⏱️ **efinance 長呼叫掛起修復** (#660) — 為所有 efinance API 呼叫引入 `_ef_call_with_timeout()` 包裝（預設 30 秒，可透過 `EFINANCE_CALL_TIMEOUT` 配置）；使用 `executor.shutdown(wait=False)` 確保超時後不再阻塞主執行緒，徹底消除 81 分鐘掛起問題
- 🛡️ **型別安全內容完整性檢查** (#660) — `check_content_integrity()` 現在將非字串型別的 `operation_advice` / `analysis_summary` 視為缺失欄位，避免下游 `get_emoji()` 因 `dict.strip()` 崩潰
- 📄 **報告儲存與通知解耦** (#660) — `_save_local_report()` 不再依賴 `send_notification` 標誌觸發，`--no-notify` 模式下本地報告照常儲存
- 🔄 **operation_advice 字典歸一化** (#660) — Pipeline 和 BacktestEngine 現在將 LLM 返回的 `dict` 格式 `operation_advice` 透過 `decision_type`（不區分大小寫）對映為標準字串，防止因模型輸出格式變化導致崩潰
- 🛡️ **runner.py usage None 防護** (#660) — `response.usage` 為 `None` 時不再丟擲 `AttributeError`，回退為 0 token 計數
- 📋 **orchestrator 靜默失敗改為日誌警告** (#660) — `IntelAgent` / `RiskAgent` 階段失敗現在記錄 `WARNING` 而非靜默跳過，便於診斷

### Notes
- ⚠️ **Multi-worker auth toggles** — runtime auth updates are process-local; multi-worker deployments must restart/roll workers to keep auth state consistent

## [3.5.0] - 2026-03-12

### Added
- 📊 **Web UI full report drawer** (Fixes #214) — history page adds "Full Report" button to display the complete Markdown analysis report in a side drawer; new `GET /api/v1/history/{record_id}/markdown` endpoint
- 📊 **LLM cost tracking** — all LLM calls (analysis, agent, market review) recorded in `llm_usage` table; new `GET /api/v1/usage/summary?period=today|month|all` endpoint returns aggregated token usage by call type and model
- 🔍 **SearXNG search provider** (Fixes #550) — quota-free self-hosted search fallback; priority: Bocha > Tavily > Brave > SerpAPI > MiniMax > SearXNG
- 🔍 **MiniMax web search provider** — `MiniMaxSearchProvider` with circuit breaker (3 failures → 300s cooldown) and dual time-filtering; configured via `MINIMAX_API_KEYS`
- 🤖 **Agent models discovery API** — `GET /api/v1/agent/models` returns available model deployments (primary/fallback/source/api_base) for Web UI model selector
- 🤖 **Agent chat export & send** (#495) — export conversation to .md file; send to configured notification channels; new `POST /api/v1/agent/chat/send`
- 🤖 **Agent background execution** (#495) — analysis continues when switching pages; badge notification on completion; auto-cancel in-progress stream on session switch
- 📝 **Report Engine P0** — Pydantic schema validation for LLM JSON; Jinja2 templates (markdown/wechat/brief) with legacy fallback; content integrity checks with retry; brief mode (`REPORT_TYPE=brief`); history signal comparison
- 📦 **Smart import** — multi-source import from image/CSV/Excel/clipboard; Vision LLM extracts code+name+confidence; name→code resolver (local map + pinyin + AkShare); confidence-tiered confirmation
- ⚙️ **GitHub Actions LiteLLM config** — workflow supports `LITELLM_CONFIG`/`LITELLM_CONFIG_YAML` for flexible AI provider configuration
- ⚙️ **Config engine refactor & system API** (#602) — unified config registry, validation and API exposure
- 📖 **LLM configuration guide** — new `docs/LLM_CONFIG_GUIDE.md` covering 3-tier config, quick start, Vision/Agent/troubleshooting

### Fixed
- 🐛 **analyze_trend always reports No historical data** (#600) — now fetches from DB/DataFetcher instead of broken `get_analysis_context`
- 🐛 **Chip structure fallback when LLM omits it** (#589) — auto-fills from data source chip data for consistent display across models
- 🐛 **History sniper points show raw text** (#452) — prioritizes original strings over compressed numeric values
- 🐛 **GitHub Actions ENABLE_CHIP_DISTRIBUTION configurable** (#617) — no longer hardcoded, supports vars/secrets override
- 🐛 **`.env` save preserves comments and blank lines** — Web settings no longer destroys `.env` formatting
- 🐛 **Agent model discovery fixes** — legacy mode includes LiteLLM-native providers; source detection aligned with runtime; fallback deployments no longer expanded per-key
- 🐛 **Stooq US stock previous close semantics** — no longer misuses open price as previous close
- 🐛 **Stock name prefetch regression** — prioritizes local `STOCK_NAME_MAP` before remote queries
- 🐛 **AkShare limit-up/down calculation** (#555) — fixed market analysis statistics
- 🐛 **AkShare Tencent source field index & ETF quote mapping** (#579)
- 🐛 **Pytdx stock name cache pagination** (#573) — prevents cache overflow
- 🐛 **PushPlus oversized report chunking** (#489) — auto-segments long content
- 🐛 **Agent chat cancel & switch** (#495) — cancel no longer misreports as failure; fast switch no longer overwrites stream state
- 🐛 **MiniMax search status in `/status` command** (#587)
- 🐛 **config_registry duplicate BOCHA_API_KEYS** — removed duplicate dict entry that silently overwrote config

### Changed
- 🔎 **Fetcher failure observability** — logs record start/success/failure with elapsed time, failover transitions; Efinance/Akshare include upstream endpoint and classified failure categories
- ♻️ **Data source resilience & cleanup** (#602) — fallback chain optimization
- ♻️ **Image extract API response extension** — new `items` field (code/name/confidence); `codes` preserved for backward compatibility
- ♻️ **Import parse error messages** — specific failure reasons for Excel/CSV; improved logging with file type and size

### Docs
- 📖 LLM config guide refactored for clarity (#583)
- 📖 `image-extract-prompt.md` with full prompt documentation
- 📖 AkShare fallback cache TTL documentation
## [3.4.10] - 2026-03-07

### Fixed
- 🐛 **EfinanceFetcher ETF OHLCV data** (#541, #527) — switch `_fetch_etf_data` from `ef.fund.get_quote_history` (NAV-only, no OHLCV, no `beg`/`end` params) to `ef.stock.get_quote_history`; ETFs now return proper open/high/low/close/volume/amount instead of zeros; remove obsolete NAV column mappings from `_normalize_data`
- 🐛 **tiktoken 0.12.0 `Unknown encoding cl100k_base`** (#537) — pin `tiktoken>=0.8.0,<0.12.0` in requirements.txt to avoid plugin-registration regression introduced in 0.12.0
- 🐛 **Web UI API error classification** (#540) — frontend no longer treats every HTTP 400 as the same "server/network" failure; now distinguishes Agent disabled / missing params / model-tool incompatibility / upstream LLM errors / local connection failures
- 🐛 **北交所程式碼識別失敗** (#491, #533) — 8/4/92 開頭的 6 位程式碼現正確識別為北交所；Tushare/Akshare/Yfinance 等資料來源支援 .BJ 或 bj 字首；Baostock/Pytdx 對北交所程式碼顯式切換資料來源；避免誤判上海 B 股 900xxx
- 🐛 **狙擊點位解析錯誤** (#488, #532) — 理想買進/二次買進等欄位在無「元」字時誤提取括號內技術指標數字；現先截去第一個括號後內容再提取

### Added
- **Markdown-to-image for dashboard report** (#455, #535) — 個股日報彙總支援 markdown 轉圖片推送（Telegram、WeChat、Custom、Email），與大盤覆盤行為一致
- **markdown-to-file engine** (#455) — `MD2IMG_ENGINE=markdown-to-file` 可選，對 emoji 支援更好，需 `npm i -g markdown-to-file`
- **PREFETCH_REALTIME_QUOTES** (#455) — 設為 `false` 可禁用實時行情預取，避免 efinance/akshare_em 全市場拉取
- **Stock name prefetch** (#455) — 分析前預取股票名稱，減少報告中「股票xxxxx」佔位符
- 📊 **分析報告模型標記** (#528, #534) — 在分析報告 meta、報告末尾、推送內容中展示 `model_used`（完整 LLM 模型名）；Agent 多輪呼叫時記錄並展示每輪實際使用的模型（支援 fallback 切換）

### Changed
- **Enhanced markdown-to-image failure warning** (#455) — 轉圖失敗時提示具體依賴（wkhtmltopdf 或 m2f）
- **WeChat-only image routing optimization** (#455) — 僅配置企業微信圖片時，不再對完整報告做冗餘轉圖，避免誤導性失敗日誌
- **Stock name prefetch lightweight mode** (#455) — 名稱預取階段跳過 realtime quote 查詢，減少額外網路開銷

## [3.4.9] - 2026-03-06

### Added
- 🧠 **Structured config validation** — `ConfigIssue` dataclass and `validate_structured()` with severity-aware logging; `CONFIG_VALIDATE_MODE=strict` aborts startup on errors
- 🖼️ **Vision model config** — `VISION_MODEL` and `VISION_PROVIDER_PRIORITY` for image stock extraction; provider fallback (Gemini → Anthropic → OpenAI → DeepSeek) when primary fails
- 🚀 **CLI init wizard** — `python -m dsa init` 3-step interactive bootstrap (model → data source → notification), 9 provider presets, incremental merge by default
- 🔧 **Multi-channel LLM support** with visual channel editor (#494)

### Changed
- ♻️ **Vision extraction** — migrated from gemini-3 hardcode to `litellm.completion()` with configurable model and provider fallback; `OPENAI_VISION_MODEL` deprecated in favor of `VISION_MODEL`
- ♻️ **Market analyzer** — uses `Analyzer.generate_text()` for LLM calls; fixes bypass and Anthropic `AttributeError` when using non-Router path
- ♻️ **Config validation refinements** — test_env output format syncs with `validate_structured` (severity-aware ✓/✗/⚠/·); Vision key warning when `VISION_MODEL` set but no provider API key; market_analyzer test covers `generate_market_review` fallback when `generate_text` returns None
- ⚙️ **Auto-tag workflow defaults to NO tag** — only tags when commit message explicitly contains `#patch`, `#minor`, or `#major`
- ♻️ **Formatter and notification refactor** (#516)

### Fixed
- 🐛 **STOCK_LIST not refreshed on scheduled runs** — `.env` or WebUI changes to `STOCK_LIST` now hot-reload before each scheduled analysis (#529)
- 🐛 **WebUI fails to load with MIME type error** — SPA fallback route now resolves correct `Content-Type` for JS/CSS files (#520)
- 🐛 **AstrBot sender docstring misplaced** — `import time` placed before docstring in `_send_astrbot`, causing it to become dead code
- 🐛 **Telegram Markdown link escaping** — `_convert_to_telegram_markdown` escaped `[]()` characters, breaking all Markdown links in reports
- 🐛 **Duplicate `discord_bot_status` field** in Config dataclass — second declaration silently shadowed the first
- 🧹 **Unused imports** — removed `shutil`/`subprocess` from `main.py`
- 🔧 **Config validation and Vision key check** (#525)

### Docs
- 📝 Clarified GitHub Actions non-trading-day manual run controls (`TRADING_DAY_CHECK_ENABLED` + `force_run`) for Issue #461 / PR #466

## [3.4.8] - 2026-03-02

### Fixed
- 🐛 **Desktop exe crashes on startup with `FileNotFoundError`** — PyInstaller build was missing litellm's JSON data files (e.g. `model_prices_and_context_window_backup.json`). Added `--collect-data litellm` to both Windows and macOS build scripts so the files are correctly bundled in the executable.

### CI
- 🔧 Cache Electron binaries on macOS CI runners to prevent intermittent EOF download failures when fetching `electron-vX.Y.Z-darwin-*.zip` from GitHub CDN
- 🔧 Fix macOS DMG `hdiutil Resource busy` error during desktop packaging

### Docs
- 📝 Clarify non-trading-day manual run controls for GitHub Actions (`TRADING_DAY_CHECK_ENABLED` + `force_run`) (#474)

## [3.4.7] - 2026-02-28

### Added
- 🧠 **CN/US Market Strategy Blueprint System** (#395) — market review prompt injects region-specific strategy blueprints with position sizing and risk trigger recommendations

### Fixed
- 🐛 **`TRADING_DAY_CHECK_ENABLED` env var and `--force-run` for GitHub Actions** (#466)
- 🐛 **Agent pipeline preserved resolved stock names** (#464) — placeholder names no longer leak into reports
- 🐛 **Code cleanup** (#462, Fixes #422)
- 🐛 **WebUI auto-build on startup** (#460)
- 🐛 **ARCH_ARGS unbound variable** (#458)
- 🐛 **Time zone inconsistency & right panel flash** (#439)

### Docs
- 📝 Clarify potential ambiguities in code (#343)
- 📝 ENABLE_EASTMONEY_PATCH guidance for Issue #453 (#456)

## [3.4.0] - 2026-02-27

### Added
- 📡 **LiteLLM Direct Integration + Multi API Key Support** (#454, Fixes #421 #428)
  - Removed native SDKs (google-generativeai, google-genai, anthropic); unified through `litellm>=1.80.10`
  - New config: `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `GEMINI_API_KEYS`, `ANTHROPIC_API_KEYS`, `OPENAI_API_KEYS`
  - Multi-key auto-builds LiteLLM Router (simple-shuffle) with 429 cooldown
  - **Breaking**: `.env` `GEMINI_MODEL` (no prefix) only for fallback; explicit config must include provider prefix

### Changed
- ♻️ **Notification Refactoring** (#435) — extracted 10 sender classes into `src/notification_sender/`

### Fixed
- 🐛 LLM NoneType crash, history API 422, sniper points extraction
- 🐛 Auto-build frontend on WebUI startup — `WEBUI_AUTO_BUILD` env var (default `true`)
- 🐛 Docker explicit project name (#448)
- 🐛 Bocha search SSL retry (#445, #446) — transient errors retry up to 3 times
- 🐛 Gemini google-genai SDK migration (Fixes #440, #444)
- 🐛 Mobile home page scrolling (Fixes #419, #433)
- 🐛 History list scroll reset (#431)
- 🐛 Settings save button false positive (fixes #417, #430)

## [3.3.22] - 2026-02-26

### Added
- 💬 **Chat History Persistence** (Fixes #400, #414) — `/chat` page survives refresh, sidebar session list
- 🎨 Project VI Assets — logo icon set, PSD, vector, banner (#425)
- 🚀 Desktop CI Auto-Release (#426) — Windows + macOS parallel builds

### Fixed
- 🐛 Agent Reasoning 400 & LiteLLM Proxy (fixes #409, #427)
- 🐛 Discord chunked sending (#413) — `DISCORD_MAX_WORDS` config
- 🐛 yfinance shared DataFrame (#412)
- 🐛 sniper_points parsing (#408)
- 🐛 Agent framework category missing (#406)
- 🐛 Date inconsistency & query id (fixes #322, #363)

## [3.3.12] - 2026-02-24

### Added
- 📈 **Intraday Realtime Technical Indicators** (Issue #234, #397) — MA calculated from realtime price, config: `ENABLE_REALTIME_TECHNICAL_INDICATORS`
- 🤖 **Agent Strategy Chat** (#367) — full ReAct pipeline, 11 YAML strategies, SSE streaming, multi-turn chat
- 📢 PushPlus Group Push — `PUSHPLUS_TOPIC` (#402)
- 📅 Trading Day Check (Issue #373, #375) — `TRADING_DAY_CHECK_ENABLED`, `--force-run`

### Fixed
- 🐛 DeepSeek reasoning mode (Issue #379, #386)
- 🐛 Agent news intel persistence (Fixes #396, #405)
- 🐛 Bare except clauses replaced with `except Exception` (#398)
- 🐛 UUID fallback for HTTP non-secure context (fixes #377, #381)
- 🐛 Docker DNS resolution (Fixes #372, #374)
- 🐛 Agent session/strategy bugs — multiple follow-up fixes for #367
- 🐛 yfinance parallel download data filtering

### Changed
- Market review strategy consistency — unified cn/us template
- Agent test assertions updated (`6 -> 11`)


## [3.2.11] - 2026-02-23

### 修復（#patch）
- 🐛 **StockTrendAnalyzer 從未執行** (Issue #357)
  - 根因：`get_analysis_context` 僅返回 2 天資料且無 `raw_data`，pipeline 中 `raw_data in context` 始終為 False
  - 修復：Step 3 直接呼叫 `get_data_range` 獲取 90 日曆天（約 60 交易日）歷史資料用於趨勢分析
  - 改善：趨勢分析失敗時用 `logger.warning(..., exc_info=True)` 記錄完整 traceback

## [3.2.10] - 2026-02-22

### 新增
- ⚙️ 支援 `RUN_IMMEDIATELY` 配置項，設為 `true` 時定時任務觸發後立即執行一次分析，無需等待首個定時點

### 修復
- 🐛 修復 Web UI 頁面居中問題
- 🐛 修復 Settings 返回 500 錯誤

## [3.2.9] - 2026-02-22

### 修復
- 🐛 **ETF 分析僅關注指數走勢**（Issue #274）
  - 美股/港股 ETF（如 VOO、QQQ）與 A 股 ETF 不再納入基金公司層面風險（訴訟、聲譽等）
  - 搜尋維度：ETF/指數專用 risk_check、earnings、industry 查詢，避免命中基金管理人新聞
  - AI 提示：指數型標的分析約束，`risk_alerts` 不得出現基金管理人公司經營風險

## [3.2.8] - 2026-02-21

### 修復
- 🐛 **BOT 與 WEB UI 股票程式碼大小寫統一**（Issue #355）
  - BOT `/analyze` 與 WEB UI 觸發分析的股票程式碼統一為大寫（如 `aapl` → `AAPL`）
  - 新增 `canonical_stock_code()`，在 BOT、API、Config、CLI、task_queue 入口處規範化
  - 歷史記錄與任務去重邏輯可正確識別同一股票（大小寫不再影響）

## [3.2.7] - 2026-02-20

### 新增
- 🔐 **Web 頁面密碼驗證**（Issue #320, #349）
  - 支援 `ADMIN_AUTH_ENABLED=true` 啟用 Web 登入保護
  - 首次訪問在網頁設定初始密碼；支援「系統設定 > 修改密碼」和 CLI `python -m src.auth reset_password` 重置

## [3.2.6] - 2026-02-20
### ⚠️ 破壞性變更（Breaking Changes）

- **歷史記錄 API 變更 (Issue #322)**
  - 路由變更：`GET /api/v1/history/{query_id}` → `GET /api/v1/history/{record_id}`
  - 引數變更：`query_id` (字串) → `record_id` (整數)
  - 新聞介面變更：`GET /api/v1/history/{query_id}/news` → `GET /api/v1/history/{record_id}/news`
  - 原因：`query_id` 在批次分析時可能重複，無法唯一標識單條歷史記錄。改用資料庫主鍵 `id` 確保唯一性
  - 影響範圍：使用舊版歷史詳情 API 的所有客戶端需同步更新

### 修復
- 修復美股（如 ADBE）技術指標矛盾：akshare 美股復權資料異常，統一美股歷史資料來源為 YFinance（Issue #311）
- 🐛 **歷史記錄查詢和顯示問題 (Issue #322)**
  - 修復歷史記錄列表查詢中日期不一致問題：使用明天作為 endDate，確保包含今天全天的資料
  - 修復伺服器 UI 報告選擇問題：原因是多條記錄共享同一 `query_id`，導致總是顯示第一條。現改用 `analysis_history.id` 作為唯一標識
  - 歷史詳情、新聞介面及前端元件已全面適配 `record_id`
  - 新增後臺輪詢（每 30s）與頁面可見性變更時靜默重新整理歷史列表，確保 CLI 發起的分析完成後前端能及時同步，使用 `silent` 模式避免觸發 loading 狀態
- 🐛 **美股指數實時行情與日線資料** (Issue #273)
  - 修復 SPX、DJI、IXIC、NDX、VIX、RUT 等美股指數無法獲取實時行情的問題
  - 新增 `us_index_mapping` 模組，將使用者輸入（如 SPX）對映為 Yahoo Finance 符號（如 ^GSPC）
  - 美股指數與美股股票日線資料直接路由至 YfinanceFetcher，避免遍歷不支援的資料來源
  - 消除重複的美股識別邏輯，統一使用 `is_us_stock_code()` 函式

### 最佳化
- 🎨 **首頁輸入欄與 Market Sentiment 佈局對齊最佳化**
  - 股票程式碼輸入框左緣與歷史記錄 glass-card 框左對齊
  - 分析按鈕右緣與 Market Sentiment 外框右對齊
  - Market Sentiment 卡片向下拉伸填滿格子，消除與 STRATEGY POINTS 之間的空隙
  - 窄屏時輸入欄填滿寬度，響應式對齊保持一致

## [3.2.5] - 2026-02-19

### 新增
- 🌍 **大盤覆盤可選區域**（Issue #299）
  - 支援 `MARKET_REVIEW_REGION` 環境變數：`cn`（A股）、`us`（美股）、`both`（兩者）
  - us 模式使用 SPX/納斯達克/道指/VIX 等指數；both 模式可同時覆盤 A 股與美股
  - 預設 `cn`，保持向後相容

## [3.2.4] - 2026-02-18

### 修復
- 🐛 **統一美股資料來源為 YFinance**（Issue #311）
  - akshare 美股復權資料異常，統一美股歷史資料來源為 YFinance
  - 修復 ADBE 等美股股票技術指標矛盾問題

## [3.2.3] - 2026-02-18

### 修復
- 🐛 **標普500實時資料缺失**（Issue #273）
  - 修復 SPX、DJI、IXIC、NDX、VIX、RUT 等美股指數無法獲取實時行情的問題
  - 新增 `us_index_mapping` 模組，將使用者輸入（如 SPX）對映為 Yahoo Finance 符號（如 `^GSPC`）
  - 美股指數與美股股票日線資料直接路由至 YfinanceFetcher，避免遍歷不支援的資料來源

## [3.2.2] - 2026-02-16

### 新增
- 📊 **PE 指標支援**（Issue #296）
  - AI System Prompt 增加 PE 估值關注
- 📰 **新聞時效性篩查**（Issue #296）
  - `NEWS_MAX_AGE_DAYS`：新聞最大時效（天），預設 3，避免使用過時資訊
- 📈 **強勢趨勢股乖離率放寬**（Issue #296）
  - `BIAS_THRESHOLD`：乖離率閾值（%），預設 5.0，可配置
  - 強勢趨勢股（多頭排列且趨勢強度 ≥70）自動放寬乖離率到 1.5 倍

## [3.2.1] - 2026-02-16

### 新增
- 🔧 **東財介面補丁可配置開關**
  - 支援 `EFINANCE_PATCH_ENABLED` 環境變數開關東財介面補丁（預設 `true`）
  - 補丁不可用時可降級關閉，避免影響主流程

## [3.2.0] - 2026-02-15

### 新增
- 🔒 **CI 門禁統一（P0）**
  - 新增 `scripts/ci_gate.sh` 作為後端門禁單一入口
  - 主 CI 改為 `backend-gate`、`docker-build`、`web-gate` 三段式
  - CI 觸發改為所有 PR，避免 Required Checks 因路徑過濾缺失而卡住合併
  - `web-gate` 支援前端路徑變更按需觸發
  - 新增 `network-smoke` 工作流承載非阻斷網路場景迴歸
- 📦 **釋出鏈路收斂（P0）**
  - `docker-publish` 調整為 tag 主觸發，並增加發布前門禁校驗
  - 手動釋出增加 `release_tag` 輸入與 semver/changelog 強校驗
  - 釋出前新增 Docker smoke（關鍵模組匯入）
- 📝 **PR 模板升級（P0）**
  - 增加背景、範圍、驗證命令與結果、回滾方案、Issue 關聯等必填項
- 🤖 **AI 審查覆蓋增強（P0）**
  - `pr-review` 納入 `.github/workflows/**` 範圍
  - 新增 `AI_REVIEW_STRICT` 開關，可選將 AI 審查失敗升級為阻斷

## [3.1.13] - 2026-02-15

### 新增
- 📊 **僅分析結果摘要**（Issue #262）
  - 支援 `REPORT_SUMMARY_ONLY` 環境變數，設為 `true` 時只推送彙總，不含個股詳情
  - 預設 `false`，多股時適合快速瀏覽

## [3.1.12] - 2026-02-15

### 新增
- 📧 **個股與大盤覆盤合併推送**（Issue #190）
  - 支援 `MERGE_EMAIL_NOTIFICATION` 環境變數，設為 `true` 時將個股分析與大盤覆盤合併為一次推送
  - 預設 `false`，減少郵件數量、降低被識別為垃圾郵件的風險

## [3.1.11] - 2026-02-15

### 新增
- 🤖 **Anthropic Claude API 支援**（Issue #257）
  - 支援 `ANTHROPIC_API_KEY`、`ANTHROPIC_MODEL`、`ANTHROPIC_TEMPERATURE`、`ANTHROPIC_MAX_TOKENS`
  - AI 分析優先順序：Gemini > Anthropic > OpenAI
- 📷 **從圖片識別股票程式碼**（Issue #257）
  - 上傳自選股截圖，透過 Vision LLM 自動提取股票程式碼
  - API: `POST /api/v1/stocks/extract-from-image`；支援 JPEG/PNG/WebP/GIF，最大 5MB
  - 支援 `OPENAI_VISION_MODEL` 單獨配置圖片識別模型
- ⚙️ **通達信資料來源手動配置**（Issue #257）
  - 支援 `PYTDX_HOST`、`PYTDX_PORT` 或 `PYTDX_SERVERS` 配置自建通達信伺服器

## [3.1.10] - 2026-02-15

### 新增
- ⚙️ **立即執行配置**（Issue #332）
  - 支援 `RUN_IMMEDIATELY` 環境變數，`true` 時定時任務啟動後立即執行一次
- 🐛 修復 Docker 構建問題

## [3.1.9] - 2026-02-14

### 新增
- 🔌 **東財介面補丁機制**
  - 新增 `patch/eastmoney_patch.py` 修復 efinance 上游介面變更
  - 不影響其他資料來源的正常執行

## [3.1.8] - 2026-02-14

### 新增
- 🔐 **Webhook 證書校驗開關**（Issue #265）
  - 支援 `WEBHOOK_VERIFY_SSL` 環境變數，可關閉 HTTPS 證書校驗以支援自簽名證書
  - 預設保持校驗，關閉存在 MITM 風險，僅建議在可信內網使用

## [3.1.7] - 2026-02-14

### 修復
- 🐛 修復包匯入錯誤（package import error）

## [3.1.6] - 2026-02-13

### 修復
- 🐛 修復 `news_intel` 中 `query_id` 不一致問題

## [3.1.5] - 2026-02-13

### 新增
- 📷 **Markdown 轉圖片通知**（Issue #289）
  - 支援 `MARKDOWN_TO_IMAGE_CHANNELS` 配置，對 Telegram、企業微信、自定義 Webhook（Discord）、郵件傳送圖片格式報告
  - 郵件為內聯附件，增強對不支援 HTML 客戶端的相容性
  - 需安裝 `wkhtmltopdf` 和 `imgkit`

## [3.1.4] - 2026-02-12

### 新增
- 📧 **股票分組發往不同郵箱**（Issue #268）
  - 支援 `STOCK_GROUP_N` + `EMAIL_GROUP_N` 配置，不同股票組報告傳送到對應郵箱
  - 大盤覆盤發往所有配置的郵箱

## [3.1.3] - 2026-02-12

### 修復
- 🐛 修復 Docker 內執行時透過頁面修改配置報錯 `[Errno 16] Device or resource busy` 的問題

## [3.1.2] - 2026-02-11

### 修復
- 🐛 修復 Docker 一致性問題，解決關鍵批次處理與通知 Bug

## [3.1.1] - 2026-02-11

### 變更
- ♻️ `API_HOST` → `WEBUI_HOST`：Docker Compose 配置項統一

## [3.1.0] - 2026-02-11

### 新增
- 📊 **ETF 支援增強與程式碼規範化**
  - 統一各資料來源 ETF 程式碼處理邏輯
  - 新增 `canonical_stock_code()` 統一程式碼格式，確保資料來源路由正確

## [3.0.5] - 2026-02-08

### 修復
- 🐛 修復訊號 emoji 與建議不一致的問題（複合建議如"賣出/觀望"未正確對映）
- 🐛 修復 `*ST` 股票名在微信/Dashboard 中 markdown 轉義問題
- 🐛 修復 `idx.amount` 為 None 時大盤覆盤 TypeError
- 🐛 修複分析 API 返回 `report=None` 及 ReportStrategy 型別不一致問題
- 🐛 修復 Tushare 返回型別錯誤（dict → UnifiedRealtimeQuote）及 API 端點指向

### 新增
- 📊 大盤覆盤報告注入結構化資料（漲跌統計、指數表格、板塊排名）
- 🔍 搜尋結果 TTL 快取（500 條上限，FIFO 淘汰）
- 🔧 Tushare Token 存在時自動注入實時行情優先順序
- 📰 新聞摘要截斷長度 50→200 字

### 最佳化
- ⚡ 補充行情欄位請求限制為最多 1 次，減少無效請求

## [3.0.4] - 2026-02-07

### 新增
- 📈 **回測引擎** (PR #269)
  - 新增基於歷史分析記錄的回測系統，支援收益率、勝率、最大回撤等指標評估
  - WebUI 整合回測結果展示

## [3.0.3] - 2026-02-07

### 修復
- 🐛 修復狙擊點位資料解析錯誤問題 (PR #271)

## [3.0.2] - 2026-02-06

### 新增
- ✉️ 可配置郵件傳送者名稱 (PR #272)
- 🌐 外國股票支援英文關鍵詞搜尋

## [3.0.1] - 2026-02-06

### 修復
- 🐛 修復 ETF 實時行情獲取、市場資料回退、企業微信訊息分塊問題
- 🔧 CI 流程簡化

## [3.0.0] - 2026-02-06

### 移除
- 🗑️ **移除舊版 WebUI**
  - 刪除基於 `http.server.ThreadingHTTPServer` 的舊版 WebUI（`web/` 包）
  - 舊版 WebUI 的功能已完全被 FastAPI（`api/`）+ React 前端替代
  - `--webui` / `--webui-only` 命令列引數標記為棄用，自動重定向到 `--serve` / `--serve-only`
  - `WEBUI_ENABLED` / `WEBUI_HOST` / `WEBUI_PORT` 環境變數保持相容，自動轉發到 FastAPI 服務
  - `webui.py` 保留為相容入口，啟動時直接呼叫 FastAPI 後端
  - Docker Compose 中移除 `webui` 服務定義，統一使用 `server` 服務

### 變更
- ♻️ **服務層重構**
  - 將 `web/services.py` 中的非同步任務服務遷移至 `src/services/task_service.py`
  - Bot 分析命令（`bot/commands/analyze.py`）改為使用 `src.services.task_service`
  - Docker 環境變數 `WEBUI_HOST`/`WEBUI_PORT` 更名為 `API_HOST`/`API_PORT`（舊名仍相容）

## [2.3.0] - 2026-02-01

### 新增
- 🇺🇸 **增強美股支援** (Issue #153)
  - 實現基於 Akshare 的美股歷史資料獲取 (`ak.stock_us_daily()`)
  - 實現基於 Yfinance 的美股實時行情獲取（優先策略）
  - 增加對不支援資料來源（Tushare/Baostock/Pytdx/Efinance）的美股程式碼過濾和快速降級

### 修復
- 🐛 修復 AMD 等美股程式碼被誤識別為 A 股的問題 (Issue #153)

## [2.2.5] - 2026-02-01

### 新增
- 🤖 **AstrBot 訊息推送** (PR #217)
  - 新增 AstrBot 通知通道，支援推送到 QQ 和微信
  - 支援 HMAC SHA256 簽名驗證，確保通訊安全
  - 透過 `ASTRBOT_URL` 和 `ASTRBOT_TOKEN` 配置

## [2.2.4] - 2026-02-01

### 新增
- ⚙️ **可配置資料來源優先順序** (PR #215)
  - 支援透過環境變數（如 `YFINANCE_PRIORITY=0`）動態調整資料來源優先順序
  - 無需修改程式碼即可優先使用特定資料來源（如 Yahoo Finance）

## [2.2.3] - 2026-01-31

### 修復
- 📦 更新 requirements.txt，增加 `lxml_html_clean` 依賴以解決相容性問題

## [2.2.2] - 2026-01-31

### 修復
- 🐛 修復代理配置區分大小寫問題 (fixes #211)

## [2.2.1] - 2026-01-31

### 修復
- 🐛 **YFinance 相容性修復** (PR #210, fixes #209)
  - 修復新版 yfinance 返回 MultiIndex 列名導致的資料解析錯誤

## [2.2.0] - 2026-01-31

### 新增
- 🔄 **多源回退策略增強**
  - 實現了更健壯的資料獲取回退機制 (feat: multi-source fallback strategy)
  - 最佳化了資料來源故障時的自動切換邏輯

### 修復
- 🐛 修復 analyzer 執行後無法透過改 .env 檔案的 stock_list 內容調整跟蹤的股票

## [2.1.14] - 2026-01-31

### 文件
- 📝 更新 README 和最佳化 auto-tag 規則

## [2.1.13] - 2026-01-31

### 修復
- 🐛 **Tushare 優先順序與實時行情** (Fixed #185)
  - 修復 Tushare 資料來源優先順序設定問題
  - 修復 Tushare 實時行情獲取功能

## [2.1.12] - 2026-01-30

### 修復
- 🌐 修復代理配置在某些情況下的區分大小寫問題
- 🌐 修復本地環境禁用代理的邏輯

## [2.1.11] - 2026-01-30

### 最佳化
- 🚀 **飛書訊息流最佳化** (PR #192)
  - 最佳化飛書 Stream 模式的訊息型別處理
  - 修改 Stream 訊息模式預設為關閉，防止配置錯誤執行時報錯

## [2.1.10] - 2026-01-30

### 合併
- 📦 合併 PR #154 貢獻

## [2.1.9] - 2026-01-30

### 新增
- 💬 **微信文字訊息支援** (PR #137)
  - 新增微信推送的純文字訊息型別支援
  - 新增 `WECHAT_MSG_TYPE` 配置項

## [2.1.8] - 2026-01-30

### 修復
- 🐛 修正日誌中 API 提供商顯示錯誤 (PR #197)

## [2.1.7] - 2026-01-30

### 修復
- 🌐 禁用本地環境的代理設定，避免網路連線問題

## [2.1.6] - 2026-01-29

### 新增
- 📡 **Pytdx 資料來源 (Priority 2)**
  - 新增通達信資料來源，免費無需註冊
  - 多伺服器自動切換
  - 支援實時行情和歷史資料
- 🏷️ **多源股票名稱解析**
  - DataFetcherManager 新增 `get_stock_name()` 方法
  - 新增 `batch_get_stock_names()` 批次查詢
  - 自動在多資料來源間回退
  - Tushare 和 Baostock 新增股票名稱/列表方法
- 🔍 **增強搜尋回退**
  - 新增 `search_stock_price_fallback()` 用於資料來源全部失敗時
  - 新增搜尋維度：市場分析、行業分析
  - 最大搜尋次數從 3 增加到 5
  - 改進搜尋結果格式（每維度 4 條結果）

### 改進
- 更新搜尋查詢模板以提高相關性
- 增強 `format_intel_report()` 輸出結構

## [2.1.5] - 2026-01-29

### 新增
- 📡 新增 Pytdx 資料來源和多源股票名稱解析功能

## [2.1.4] - 2026-01-29

### 文件
- 📝 更新贊助商資訊

## [2.1.3] - 2026-01-28

### 文件
- 📝 重構 README 佈局
- 🌐 新增繁體中文翻譯 (README_CHT.md)

### 修復
- 🐛 修復 WebUI 無法輸入美股程式碼問題
  - 輸入框邏輯改成所有字母都轉換成大寫
  - 支援 `.` 的輸入（如 `BRK.B`）

## [2.1.2] - 2026-01-27

### 修復
- 🐛 修復個股分析推送失敗和報告路徑問題 (fixes #166)
- 🐛 修改 CR 錯誤，確保微信訊息最大位元組配置生效

## [2.1.1] - 2026-01-26

### 新增
- 🔧 新增 GitHub Actions auto-tag 工作流
- 📡 新增 yfinance 兜底資料來源及資料缺失警告

### 修復
- 🐳 修復 docker-compose 路徑和文件命令
- 🐳 Dockerfile 補充 copy src 資料夾 (fixes #145)

## [2.1.0] - 2026-01-25

### 新增
- 🇺🇸 **美股分析支援**
  - 支援美股程式碼直接輸入（如 `AAPL`, `TSLA`）
  - 使用 YFinance 作為美股資料來源
- 📈 **MACD 和 RSI 技術指標**
  - MACD：趨勢確認、金叉死叉訊號（零軸上金叉⭐、金叉✅、死叉❌）
  - RSI：超買超賣判斷（超賣⭐、強勢✅、超買⚠️）
  - 指標訊號納入綜合評分系統
- 🎮 **Discord 推送支援** (PR #124, #125, #144)
  - 支援 Discord Webhook 和 Bot API 兩種方式
  - 透過 `DISCORD_WEBHOOK_URL` 或 `DISCORD_BOT_TOKEN` + `DISCORD_MAIN_CHANNEL_ID` 配置
- 🤖 **機器人命令互動**
  - 釘釘機器人支援 `/分析 股票程式碼` 命令觸發分析
  - 支援 Stream 長連線模式
- 🌡️ **AI 溫度引數可配置** (PR #142)
  - 支援自定義 AI 模型溫度引數
- 🐳 **Zeabur 部署支援**
  - 新增 Zeabur 映象部署工作流
  - 支援 commit hash 和 latest 雙標籤

### 重構
- 🏗️ **專案結構最佳化**
  - 核心程式碼移至 `src/` 目錄，根目錄更清爽
  - 文件移至 `docs/` 目錄
  - Docker 配置移至 `docker/` 目錄
  - 修復所有 import 路徑，保持向後相容
- 🔄 **資料來源架構升級**
  - 新增資料來源熔斷機制，單資料來源連續失敗自動切換
  - 實時行情快取最佳化，批次預取減少 API 呼叫
  - 網路代理智慧分流，國內介面自動直連
- 🤖 Discord 機器人重構為平臺介面卡架構

### 修復
- 🌐 **網路穩定性增強**
  - 自動檢測代理配置，對國內行情介面強制直連
  - 修復 EfinanceFetcher 偶發的 `ProtocolError`
  - 增加對底層網路錯誤的捕獲和重試機制
- 📧 **郵件渲染最佳化**
  - 修復郵件中表格不渲染問題 (#134)
  - 最佳化郵件排版，更緊湊美觀
- 📢 **企業微信推送修復**
  - 修復大盤覆盤推送不完整問題
  - 增強訊息分割邏輯，支援更多標題格式
  - 增加分批傳送間隔，避免限流丟失
- 👷 **CI/CD 修復**
  - 修復 GitHub Actions 中路徑引用的錯誤

## [2.0.0] - 2026-01-24

### 新增
- 🇺🇸 **美股分析支援**
  - 支援美股程式碼直接輸入（如 `AAPL`, `TSLA`）
  - 使用 YFinance 作為美股資料來源
- 🤖 **機器人命令互動** (PR #113)
  - 釘釘機器人支援 `/分析 股票程式碼` 命令觸發分析
  - 支援 Stream 長連線模式
  - 支援選擇精簡報告或完整報告
- 🎮 **Discord 推送支援** (PR #124)
  - 支援 Discord Webhook 推送
  - 新增 Discord 環境變數到工作流

### 修復
- 🐳 修復 WebUI 在 Docker 中繫結 0.0.0.0 (fixed #118)
- 🔔 修復飛書長連線通知問題
- 🐛 修復 `analysis_delay` 未定義錯誤
- 🔧 啟動時 config.py 檢測通知通道，修復已配置自定義通道情況下仍然提示未配置問題

### 改進
- 🔧 最佳化 Tushare 優先順序判斷邏輯，提升封裝性
- 🔧 修復 Tushare 優先順序提升後仍排在 Efinance 之後的問題
- ⚙️ 配置 TUSHARE_TOKEN 時自動提升 Tushare 資料來源優先順序
- ⚙️ 實現 4 個使用者反饋 issue (#112, #128, #38, #119)

## [1.6.0] - 2026-01-19

### 新增
- 🖥️ WebUI 管理介面及 API 支援（PR #72）
  - 全新 Web 架構：分層設計（Server/Router/Handler/Service）
  - 核心 API：支援 `/analysis` (觸發分析), `/tasks` (查詢進度), `/health` (健康檢查)
  - 互動介面：支援頁面直接輸入程式碼並觸發分析，實時展示進度
  - 執行模式：新增 `--webui-only` 模式，僅啟動 Web 服務
  - 解決了 [#70](https://github.com/ZhuLinsen/daily_stock_analysis/issues/70) 的核心需求（提供觸發分析的介面）
- ⚙️ GitHub Actions 配置靈活性增強（[#79](https://github.com/ZhuLinsen/daily_stock_analysis/issues/79)）
  - 支援從 Repository Variables 讀取非敏感配置（如 STOCK_LIST, GEMINI_MODEL）
  - 保持對 Secrets 的向下相容

### 修復
- 🐛 修復企業微信/飛書報告截斷問題（[#73](https://github.com/ZhuLinsen/daily_stock_analysis/issues/73)）
  - 移除 notification.py 中不必要的長度硬截斷邏輯
  - 依賴底層自動分片機制處理長訊息
- 🐛 修復 GitHub Workflow 環境變數缺失（[#80](https://github.com/ZhuLinsen/daily_stock_analysis/issues/80)）
  - 修復 `CUSTOM_WEBHOOK_BEARER_TOKEN` 未正確傳遞到 Runner 的問題

## [1.5.0] - 2026-01-17

### 新增
- 📲 單股推送模式（[#55](https://github.com/ZhuLinsen/daily_stock_analysis/issues/55)）
  - 每分析完一隻股票立即推送，不用等全部分析完
  - 命令列引數：`--single-notify`
  - 環境變數：`SINGLE_STOCK_NOTIFY=true`
- 🔐 自定義 Webhook Bearer Token 認證（[#51](https://github.com/ZhuLinsen/daily_stock_analysis/issues/51)）
  - 支援需要 Token 認證的 Webhook 端點
  - 環境變數：`CUSTOM_WEBHOOK_BEARER_TOKEN`

## [1.4.0] - 2026-01-17

### 新增
- 📱 Pushover 推送支援（PR #26）
  - 支援 iOS/Android 跨平臺推送
  - 透過 `PUSHOVER_USER_KEY` 和 `PUSHOVER_API_TOKEN` 配置
- 🔍 博查搜尋 API 整合（PR #27）
  - 中文搜尋最佳化，支援 AI 摘要
  - 透過 `BOCHA_API_KEYS` 配置
- 📊 Efinance 資料來源支援（PR #59）
  - 新增 efinance 作為資料來源選項
- 🇭🇰 港股支援（PR #17）
  - 支援 5 位程式碼或 HK 字首（如 `hk00700`、`hk1810`）

### 修復
- 🔧 飛書 Markdown 渲染最佳化（PR #34）
  - 使用互動卡片和格式化器修復渲染問題
- ♻️ 股票列表熱過載（PR #42 修復）
  - 分析前自動過載 `STOCK_LIST` 配置
- 🐛 釘釘 Webhook 20KB 限制處理
  - 長訊息自動分塊傳送，避免被截斷
- 🔄 AkShare API 重試機制增強
  - 新增失敗快取，避免重複請求失敗介面

### 改進
- 📝 README 精簡最佳化
  - 高階配置移至 `docs/full-guide.md`


## [1.3.0] - 2026-01-12

### 新增
- 🔗 自定義 Webhook 支援
  - 支援任意 POST JSON 的 Webhook 端點
  - 自動識別釘釘、Discord、Slack、Bark 等常見服務格式
  - 支援配置多個 Webhook（逗號分隔）
  - 透過 `CUSTOM_WEBHOOK_URLS` 環境變數配置

### 修復
- 📝 企業微信長訊息分批傳送
  - 解決自選股過多時內容超過 4096 字元限制導致推送失敗的問題
  - 智慧按股票分析塊分割，每批新增分頁標記（如 1/3, 2/3）
  - 批次間隔 1 秒，避免觸發頻率限制

## [1.2.0] - 2026-01-11

### 新增
- 📢 多通道推送支援
  - 企業微信 Webhook
  - 飛書 Webhook（新增）
  - 郵件 SMTP（新增）
  - 自動識別通道型別，配置更簡單

### 改進
- 統一使用 `NOTIFICATION_URL` 配置，相容舊的 `WECHAT_WEBHOOK_URL`
- 郵件支援 Markdown 轉 HTML 渲染

## [1.1.0] - 2026-01-11

### 新增
- 🤖 OpenAI 相容 API 支援
  - 支援 DeepSeek、通義千問、Moonshot、智譜 GLM 等
  - Gemini 和 OpenAI 格式二選一
  - 自動降級重試機制

## [1.0.0] - 2026-01-10

### 新增
- 🎯 AI 決策儀表盤分析
  - 一句話核心結論
  - 精確買進/止損/目標點位
  - 檢查清單（✅⚠️❌）
  - 分持股建議（空倉者 vs 持股者）
- 📊 大盤覆盤功能
  - 主要指數行情
  - 漲跌統計
  - 板塊漲跌榜
  - AI 生成覆盤報告
- 🔍 多資料來源支援
  - AkShare（主資料來源，免費）
  - Tushare Pro
  - Baostock
  - YFinance
- 📰 新聞搜尋服務
  - Tavily API
  - SerpAPI
- 💬 企業微信機器人推送
- ⏰ 定時任務排程
- 🐳 Docker 部署支援
- 🚀 GitHub Actions 零成本部署

### 技術特性
- Gemini AI 模型（gemini-3-flash-preview）
- 429 限流自動重試 + 模型切換
- 請求間延時防封禁
- 多 API Key 負載均衡
- SQLite 本地資料儲存

---

[Unreleased]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.20.0...HEAD
[3.20.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.19.0...v3.20.0
[3.19.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.18.0...v3.19.0
[3.18.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.1...v3.18.0
[3.17.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.0...v3.17.1
[3.17.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.16.0...v3.17.0
[3.16.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.15.0...v3.16.0
[3.15.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.2...v3.15.0
[3.14.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.1...v3.14.2
[3.14.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.0...v3.14.1
[3.14.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.13.0...v3.14.0
[3.13.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.12.0...v3.13.0
[3.12.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.11.0...v3.12.0
[3.11.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.1...v3.11.0
[3.10.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.0...v3.10.1
[3.10.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.9.0...v3.10.0
[3.9.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.8.0...v3.9.0
[3.8.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.7.0...v3.8.0
[3.7.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.6.0...v3.7.0
[3.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.5.0...v3.6.0
[3.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.10...v3.5.0
[3.4.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.9...v3.4.10
[3.4.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.8...v3.4.9
[3.4.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.7...v3.4.8
[3.4.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.0...v3.4.7
[3.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.22...v3.4.0
[3.3.22]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.12...v3.3.22
[3.3.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.11...v3.3.12
[3.2.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.10...v3.2.11
[2.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.5...v2.3.0
[2.2.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.4...v2.2.5
[2.2.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.3...v2.2.4
[2.2.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.2...v2.2.3
[2.2.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.14...v2.2.0
[2.1.14]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.13...v2.1.14
[2.1.13]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.12...v2.1.13
[2.1.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.11...v2.1.12
[2.1.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.10...v2.1.11
[2.1.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.9...v2.1.10
[2.1.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.8...v2.1.9
[2.1.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.7...v2.1.8
[2.1.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.6...v2.1.7
[2.1.6]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.5...v2.1.6
[2.1.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.4...v2.1.5
[2.1.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.3...v2.1.4
[2.1.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.2...v2.1.3
[2.1.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.1...v2.1.2
[2.1.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.6.0...v2.0.0
[1.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v1.0.0
