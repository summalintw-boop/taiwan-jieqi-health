# LINE 每日推播說明（原型）

每天早上把「今天的日期、節氣、NCDR 天氣類型、該地區最低／最高溫、風險中以上的疾病與高危險群」整理成一則 LINE 文字訊息。

目前狀態：**訊息產生與 `today.json` 已完成，可不用任何金鑰驗收**；實際推播要等你申請 LINE 官方帳號並把 token 放進 GitHub Secrets 才會啟動。沒有 token 時 workflow 只會在紀錄裡印出訊息，不會送給任何人。

## 一、運作方式

```
GitHub Actions（每天臺灣 06:10、14:10）
  └─ update_data.py      抓 NCDR／Open-Meteo／氣象署 → site/data.json
       └─ line_daily.py   用 risk_rules.py 算四個地區的風險 → site/today.json（含訊息文字）
  └─ line_daily.py --send 只在 06:10 那次執行；有 token 才呼叫 LINE Messaging API
```

| 檔案 | 用途 |
|---|---|
| `risk_rules.py` | `page.html` 裡 `risks()`、`parseWx()`、`tempOf()` 與節氣計算的 Python 版本 |
| `line_daily.py` | 產生 `site/today.json` 與 LINE 訊息；`--send` 時推播 |
| `check_risk_parity.py` | 檢查 Python 版與網頁 JS 版規則結果是否一致 |
| `site/today.json` | 今日摘要，發布後網址是 `https://summalintw-boop.github.io/taiwan-jieqi-health/today.json`，之後的桌面工具也可以直接讀這個檔 |

### 改規則時要注意

風險規則現在有兩份：網頁用的 `page.html`（JavaScript）與推播用的 `risk_rules.py`。**改 `page.html` 的 `risks()` 時要同步改 `risk_rules.py`**，然後執行：

```bash
python check_risk_parity.py
```

它會產生一個比對頁（印出路徑），用瀏覽器打開，最上方顯示「一致：N 項比對全部相同」才算完成。比對內容是 `data.json` 每一天 × 四個地區，加上一整年合成天氣（各種天氣類型、季節、有雨無雨、有無溫度資料），共約 2,000 項。2026/11/11 實測全部一致；故意改錯一條地區加權時會列出 109 筆差異，確認比對有效。

## 二、訊息範例（2026/11/11 實際資料產生）

北部：

```
【臺灣節令健康曆】11/11（三）北部
節氣：立冬 第 5 天
天氣類型：秋季・偏北風（NCDR 今日推估）
氣溫：臺北 16–23°C

今天要留意（風險中以上）
△ 風險中｜呼吸道感染
　高危險群：65 歲以上長者、嬰幼兒、COPD、氣喘、長照機構住民、未接種疫苗者

建議做法與 14 天日曆：https://summalintw-boop.github.io/taiwan-jieqi-health/
氣溫為 Open-Meteo 模式預報，非氣象署官方預報。草稿：內容待公共衛生及醫療專家審閱。
```

中部：

```
【臺灣節令健康曆】11/11（三）中部
節氣：立冬 第 5 天
天氣類型：秋季・偏北風（NCDR 今日推估）
氣溫：臺中 18–28°C

今天要留意（風險中以上）
△ 風險中｜呼吸道感染
　高危險群：65 歲以上長者、嬰幼兒、COPD、氣喘、長照機構住民、未接種疫苗者
△ 風險中｜空氣品質・氣喘 COPD
　高危險群：COPD、氣喘、高血壓、心臟病、中風病史、65 歲以上長者、嬰幼兒
△ 風險中｜過敏性鼻炎・蕁麻疹
　高危險群：過敏性鼻炎、過敏體質、曾有蕁麻疹者、COPD、氣喘、異位性皮膚炎

建議做法與 14 天日曆：https://summalintw-boop.github.io/taiwan-jieqi-health/
氣溫為 Open-Meteo 模式預報，非氣象署官方預報。草稿：內容待公共衛生及醫療專家審閱。
```

- ▲＝風險高、△＝風險中；「需留意」不放進訊息，避免太長，網站上看得到。
- 沒有風險中以上時，訊息寫「今天沒有風險中以上的項目。維持規律作息，依醫囑使用藥物。」
- NCDR 沒有今天的資料或資料超過 2 天沒更新時，訊息會加一行 ※ 提醒。
- 東部和網頁一樣以宜蘭測站為代表。
- 最後一行的審閱狀態直接讀 `page.html` 的 `SITE.review`，審閱完成後改那裡即可。

自己在電腦上看四個地區的訊息（不需要任何金鑰、不會推播）：

```bash
python line_daily.py
```

## 三、LINE Messaging API 做法與費用

**LINE Notify 已於 2025/3/31 停止服務**，現在要用「LINE 官方帳號＋Messaging API」。

### 推播方式

| 方式 | API | 送給誰 | 適合 |
|---|---|---|---|
| push | `/v2/bot/message/push` | 一個 userId | 試行：只送給你自己 |
| multicast | `/v2/bot/message/multicast` | 指定的 userId，一次最多 500 個 | 正式版依地區分批送 |
| broadcast | `/v2/bot/message/broadcast` | 官方帳號所有好友 | 只推一個地區時最簡單 |
| reply | 回覆使用者訊息 | 傳訊息來的人 | 使用者傳「今天」時回覆；**不算則數** |

`line_daily.py` 支援 push／multicast（`LINE_TO` 填多個 userId 時自動改用 multicast）與 broadcast。每次推播帶固定的 `X-Line-Retry-Key`（由日期＋地區＋收件設定產生），同一天重跑 workflow 時 LINE 會回 409、不會重複發送。

### 費用（臺灣，2026/11/1 起）

| 方案 | 月費（未稅） | 每月免費則數 | 超過時 |
|---|---|---|---|
| 輕用量 | 0 元 | 200 | 不能加購，超過就送不出去 |
| 中用量 | 1,000 元 | 3,000 | 不能加購，需升級 |
| 高用量 | 1,400 元 | 6,000 | 加購：第 1–50,000 則每則 0.2 元，之後 0.15 元 |

- **則數＝收件人數**：一則訊息送給 50 位好友算 50 則；封鎖帳號的人不算。
- 每天推一則、每月約 31 次：輕用量約可送 **6 位**、中用量約 **96 位**、高用量免費額度約 **193 位**，再多要加購。
- 用完額度時 API 會回錯誤，訊息不會送出（workflow 這一步設為失敗也不影響網站更新）。
- 價格資料來源是 2026/9/1 LINE 公告後的業者整理，申請前請以 LINE 官方帳號後台顯示為準。

### 四個地區怎麼分送

broadcast 會送同一則訊息給所有好友，沒辦法依地區分。可行做法：

1. **試行（現在就能用）**：push 給自己，`LINE_REGION` 設成你住的地區。
2. **小規模**：只推一個地區，用 broadcast；或手動收集同仁的 userId，按地區分組用 multicast（要再加分組設定）。
3. **正式版**：需要一個能接收 LINE webhook 的小服務（GitHub Pages 是靜態網站，收不到 webhook），讓使用者加好友時選地區、記下 userId，再依地區 multicast；同一個服務也能做「傳『今天』就回覆」（回覆不算則數）。這一步要另外評估免費的雲端函式服務，原型未包含。

## 四、上線步驟（需要你自己申請）

1. **建立 LINE 官方帳號**：到 LINE Official Account Manager 建帳號（方案先用輕用量）。
2. **啟用 Messaging API**：官方帳號後台 → 設定 → Messaging API → 啟用，會建立 LINE Developers 的 channel。
3. **發行 Channel access token**：LINE Developers Console → 該 channel → Messaging API 分頁 → Channel access token（long-lived）→ Issue。這串 token 等同帳號密碼，不要貼到任何檔案或對話。
4. **取得你自己的 userId**：LINE Developers Console → 該 channel → Basic settings → Your user ID（U 開頭 33 字元）。
5. **用手機加官方帳號好友**（掃後台的 QR code），沒加好友收不到 push。
6. **放進 GitHub**：repo → Settings → Secrets and variables → Actions
   - Secrets（加密）：`LINE_CHANNEL_ACCESS_TOKEN`＝第 3 步的 token；`LINE_TO`＝第 4 步的 userId
   - Variables（可不設）：`LINE_REGION`＝北部／中部／南部／東部（預設北部）；`LINE_MODE`＝push（預設）或 broadcast
7. **測試**：repo → Actions → update-and-deploy → Run workflow → 勾選「send_line」→ Run。看「LINE 每日推播」步驟的紀錄，出現 `push HTTP 200` 且手機收到訊息就完成。
8. 之後每天早上 06:10 的排程會自動推播（GitHub 排程常延遲 5–30 分鐘，尖峰時可能更久）。

注意：

- 內容仍是**草稿、待公衛及醫療專家審閱**；審閱完成前建議只用 push 給自己或內部同仁，不要對外 broadcast。
- `LINE_MODE=broadcast` 會送給官方帳號所有好友，設定前請確認好友名單。
- 要暫停推播：刪掉 `LINE_CHANNEL_ACCESS_TOKEN` 這個 Secret 即可，網站照常更新。

## 五、today.json 格式

```jsonc
{
  "generated": "2026-11-11T13:37+08:00",
  "date": "2026-11-11", "weekday": "三",
  "term": {"name": "立冬", "start": "2026-11-07", "day": 5, "next": "小雪", "nextStart": "2026-11-22"},
  "weather": {"season": "秋季", "type": "偏北風", "rain": false, "kind": "今日推估", "turn": false},  // 沒資料時為 null
  "notes": [],                      // 資料缺漏或過舊的提醒
  "review": "草稿：內容待公共衛生及醫療專家審閱",
  "regions": {
    "北部": {
      "station": "臺北", "tmin": 16.3, "tmax": 23.3,
      "risks": [{"k": "resp", "lv": 2, "level": "風險中", "name": "呼吸道感染", "groups": ["..."], "why": "...", "act": "..."}],
      "message": "【臺灣節令健康曆】11/11（三）北部\n..."
    },
    "中部": {}, "南部": {}, "東部": {}
  }
}
```

`risks` 包含所有等級（需留意／風險中／風險高），依等級由高到低排序，與網頁「今日健康重點」相同。
