# 臺灣節令健康曆

依「二十四節氣」與 NCDR「AI 天氣判識日曆」的每日天氣類型，對應可能的疾病、高危險群與建議，並顯示疾管署監測趨勢與氣象署平年值。

## 檔案

| 檔案 | 用途 |
|---|---|
| `page.html` | 網頁本體（內容、樣式、程式）。要改文字或規則就改這個檔；改風險規則時要同步改 `risk_rules.py` |
| `update_data.py` | 抓資料並產生 `site/`。只用 Python 標準函式庫 |
| `risk_rules.py` | 風險規則的 Python 版（給伺服器端與 LINE 推播用），用 `check_risk_parity.py` 檢查與網頁一致 |
| `line_daily.py` | 產生 `site/today.json` 與 LINE 每日訊息，見 `LINE推播說明.md` |
| `site/index.html` | 由 `page.html` 自動包成的完整網頁，**不要手動改** |
| `site/data.json` | 自動產生的資料 |
| `site/today.json` | 自動產生的今日摘要（四個地區的風險與訊息文字） |
| `審閱清單.md` | 給公衛／醫療同仁審閱的內容清單 |
| `.github/workflows/update.yml` | GitHub Pages 自動更新與發布 |

## 資料來源（每次執行都會重抓）

1. NCDR AI 天氣判識日曆 `https://watch.ncdr.nat.gov.tw/w_207`：過去約 30 天的判識與未來約 14 天的推估。
2. 疾管署開放資料 `https://od.cdc.gov.tw/eic/`：`NHI_Influenza_like_illness.csv`、`NHI_COVID-19.csv`、`NHI_Diarrhea.csv`、`NHI_EnteroviralInfection.csv`（健保門診及住院就診人次，週資料，含縣市與年齡別）。
3. 中央氣象署氣候月平均 1991–2020：臺北、臺中、高雄、宜蘭、花蓮。

某個來源失敗時，程式會保留上一版的資料，網頁上方會顯示提醒。資料超過 2 天沒更新，網頁也會提醒。

注意：瀏覽器不能直接跨網域讀這些政府網站（沒有開 CORS），所以一定要由伺服器端定時執行 `update_data.py`。

## 上線前要改

`page.html` 裡的 `SITE`：

```js
const SITE={
  agency:'（機關名稱）',
  unit:'（承辦單位）',
  contact:'（聯絡電話／電子郵件）',
  review:'草稿：內容待公共衛生及醫療專家審閱',
};
```

審閱完成後把 `review` 改成例如「已由○○○審閱（2026/12/01）」。

## 上線方式

### A. 機關自己的網頁伺服器

1. 把整個資料夾放到伺服器。
2. 排程每天執行兩次（例如 06:10、14:10）：`python update_data.py`
3. 網站根目錄指向 `site/`。

Windows 工作排程器範例：

```bat
schtasks /Create /SC DAILY /ST 06:10 /TN JieqiHealthUpdate /TR "python C:\path\to\update_data.py"
```

### B. GitHub Pages（免費、自動更新）

1. 在 GitHub 建一個 repository，把這個資料夾的內容推上去（`main` 分支）。
2. Settings → Pages → Source 選 **GitHub Actions**。
3. Actions 會每天臺灣時間 06:10、14:10 自動更新資料並發布，網址是 `https://<帳號>.github.io/<repo>/`。

## 本機預覽

```bash
python update_data.py
```

```bash
python -m http.server 8791 --directory site
```

然後開 http://localhost:8791 。
