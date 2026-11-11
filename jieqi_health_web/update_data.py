"""臺灣節令健康曆：資料更新程式

每天執行一次，抓取三個公開來源，產生 site/data.json，並把 page.html 包成 site/index.html。

  1. NCDR AI 天氣判識日曆（https://watch.ncdr.nat.gov.tw/w_207）
  2. 疾管署開放資料：健保門診及住院就診人次（類流感、COVID-19、腹瀉、腸病毒）
  3. 中央氣象署 氣候月平均（1991–2020 平年值）：氣溫、相對濕度

用法：
    python update_data.py            # 更新資料並輸出 site/
只用 Python 標準函式庫，不需要安裝套件。
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import io
import json
import re
import ssl
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE / "site"
TW = dt.timezone(dt.timedelta(hours=8))
UA = {"User-Agent": "jieqi-health-updater/1.0"}

NCDR_URL = "https://watch.ncdr.nat.gov.tw/w_207"
CDC_BASE = "https://od.cdc.gov.tw/eic/"
CDC_SETS = {
    "ili": ("NHI_Influenza_like_illness.csv", "類流感"),
    "covid": ("NHI_COVID-19.csv", "COVID-19"),
    "diarrhea": ("NHI_Diarrhea.csv", "腹瀉"),
    "ev": ("NHI_EnteroviralInfection.csv", "腸病毒"),
}
CWA_URL = "https://www.cwa.gov.tw/V8/C/C/Statistics/MonthlyMean/MOD/Taiwan_{k}.html"
STATIONS = ["臺北", "臺中", "高雄", "花蓮", "宜蘭"]

# 疾管署縣市 → 頁面上的地區（與氣候測站對應）
REGIONS = {
    "北部": ["台北市", "新北市", "基隆市", "桃園市", "新竹市", "新竹縣"],
    "中部": ["苗栗縣", "台中市", "彰化縣", "南投縣", "雲林縣"],
    "南部": ["嘉義市", "嘉義縣", "台南市", "高雄市", "屏東縣", "澎湖縣"],
    "東部": ["宜蘭縣", "花蓮縣", "台東縣"],
}
WEEKS_KEPT = 16


# 政府網站部分憑證缺少 Subject Key Identifier，Python 3.13+ 的嚴格檢查會拒絕。
# 仍然驗證憑證鏈與主機名稱，只關掉 X509 strict 旗標。
SSL_CTX = ssl.create_default_context()
if hasattr(ssl, "VERIFY_X509_STRICT"):
    SSL_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT


def get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read()


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ").strip()


# ---------------- NCDR AI 天氣判識日曆 ----------------
def fetch_ncdr(today: dt.date) -> dict:
    page = get(NCDR_URL).decode("utf-8", "replace")
    cells = re.findall(r"<td>(.*?)</td>", page, flags=re.S)
    days = []
    for c in cells:
        m = re.search(r"<div class='date-num(-fst)?[^']*'>\s*([0-9/]+)", c)
        if not m:
            continue
        kind_txt = strip_tags("".join(re.findall(r"<span class='fst-txt'>(.*?)</span>", c)))
        st = re.search(r"<div class='status-icon'>(.*)</div>", c, flags=re.S)
        parts = [strip_tags(p) for p in re.split(r"<br\s*/?>", st.group(1))] if st else []
        days.append({
            "label": m.group(2),
            "kind": "today" if "今日" in kind_txt else ("fcst" if "未來" in kind_txt else "obs"),
            "season": parts[0] if len(parts) > 0 else "",
            "type": parts[1] if len(parts) > 1 else "",
            "solar": parts[2] if len(parts) > 2 else "",
            "rain": "wicon_rain" in c,
        })
    if not days:
        raise RuntimeError("NCDR 日曆解析不到任何日期，頁面格式可能改了")

    idx = next((i for i, d in enumerate(days) if d["kind"] == "today"), None)
    anchor = today
    if idx is None:  # 沒有「今日推估」時，以最後一個觀測日為昨天
        idx = max(i for i, d in enumerate(days) if d["kind"] == "obs") + 1
    day_num = int(days[idx]["label"].split("/")[-1]) if idx < len(days) else today.day
    # 頁面日期與執行日不同（快取或跨日）時，往前後找日數相符的那天
    for off in (0, -1, 1, -2, 2):
        if (today + dt.timedelta(days=off)).day == day_num:
            anchor = today + dt.timedelta(days=off)
            break
    for i, d in enumerate(days):
        d["date"] = (anchor + dt.timedelta(days=i - idx)).isoformat()
        d.pop("label")

    side = page.split("statistics-sidebar", 1)[-1]
    stats = {}
    for block in re.findall(r"<h3>(.*?)</h3>(.*?)(?=<h3>|$)", side, flags=re.S):
        items = re.findall(r"<span class='stat-icon[^']*'>(.*?)</span>\s*([0-9]+)天", block[1])
        if items:
            stats[strip_tags(block[0])] = {strip_tags(k): int(v) for k, v in items}
    note = strip_tags(re.search(r"<div class=\"calendar-txt\">(.*?)</div>", page, flags=re.S).group(1)) \
        if "calendar-txt" in page else ""
    return {"source": NCDR_URL, "today": anchor.isoformat(), "days": days, "stats": stats, "note": note}


# ---------------- 疾管署開放資料 ----------------
def county_region() -> dict:
    return {c: r for r, cs in REGIONS.items() for c in cs}


def fetch_cdc() -> dict:
    c2r = county_region()
    out = {}
    for key, (fname, name) in CDC_SETS.items():
        raw = get(CDC_BASE + fname, timeout=300).decode("utf-8-sig")
        rd = csv.reader(io.StringIO(raw))
        header = next(rd)
        # agg[region][(y,w)] = [opd, opd_total, opd65, opd65_total, ipd65]
        agg: dict = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0, 0]))
        for r in rd:
            if len(r) < 7:
                continue
            try:
                y, w, kind, age, county = int(r[0]), int(r[1]), r[2], r[3], r[4]
                n, tot = int(r[5]), int(r[6])
            except ValueError:
                continue
            for reg in ("全國", c2r.get(county)):
                if reg is None:
                    continue
                a = agg[reg][(y, w)]
                if kind == "門診":
                    a[0] += n; a[1] += tot
                    if age == "65+":
                        a[2] += n; a[3] += tot
                elif kind == "住院" and age == "65+":
                    a[4] += n
        regions = {}
        for reg, series in agg.items():
            weeks = sorted(series)
            last = weeks[-WEEKS_KEPT:]
            rows = [{"y": y, "w": w, "opd": series[(y, w)][0], "tot": series[(y, w)][1],
                     "opd65": series[(y, w)][2], "tot65": series[(y, w)][3], "ipd65": series[(y, w)][4]}
                    for (y, w) in last]
            ly, lw = last[-1]
            prev = series.get((ly - 1, lw))
            regions[reg] = {"weeks": rows,
                            "lastYear": {"y": ly - 1, "w": lw, "opd": prev[0], "tot": prev[1],
                                         "opd65": prev[2], "ipd65": prev[4]} if prev else None}
        out[key] = {"name": name, "file": CDC_BASE + fname, "columns": header, "regions": regions}
    return out


# ---------------- 中央氣象署 平年值 ----------------
def fetch_cwa() -> dict:
    res = {"source": "https://www.cwa.gov.tw/V8/C/C/Statistics/monthlymean.html", "stations": {}}
    for k, field in (("tx", "t"), ("rh", "h")):
        raw = get(CWA_URL.format(k=k)).decode("utf-8", "replace")
        text = html.unescape(re.sub(r"<[^>]+>", " ", raw)).replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text)
        for st in STATIONS:
            m = re.search(st + r" ((?:-?[0-9.]+ ){13})([0-9]{4}~[0-9]{4})", text)
            if not m:
                raise RuntimeError(f"氣象署 {k} 找不到測站 {st}")
            vals = [float(v) for v in m.group(1).split()]
            s = res["stations"].setdefault(st, {})
            s[field] = vals[:12]
            s[field + "Year"] = vals[12]
            s["period"] = m.group(2).replace("~", "–")
    return res


# ---------------- 每日最高／最低溫（Open-Meteo，免金鑰） ----------------
# 過去 31 天為模式分析值，今天起 16 天為模式預報，非中央氣象署官方預報。
TEMP_POINTS = {"臺北": (25.04, 121.51), "臺中": (24.15, 120.68), "高雄": (22.63, 120.30),
               "宜蘭": (24.76, 121.75), "花蓮": (23.98, 121.61)}
TEMP_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&daily=temperature_2m_max,temperature_2m_min&timezone=Asia%2FTaipei&past_days=31&forecast_days=16")


def fetch_temp() -> dict:
    names = list(TEMP_POINTS)
    url = TEMP_URL.format(lat=",".join(str(TEMP_POINTS[n][0]) for n in names),
                          lon=",".join(str(TEMP_POINTS[n][1]) for n in names))
    res = json.loads(get(url).decode("utf-8"))
    if isinstance(res, dict):
        res = [res]
    out = {"source": "https://open-meteo.com/", "note": "Open-Meteo 模式資料，過去日期為分析值、未來為預報；非中央氣象署官方預報",
           "stations": {}}
    for n, r in zip(names, res):
        d = r["daily"]
        out["stations"][n] = {t: [mx, mn] for t, mx, mn in zip(d["time"], d["temperature_2m_max"], d["temperature_2m_min"])
                              if mx is not None and mn is not None}
    return out


def build_site() -> None:
    frag = (HERE / "page.html").read_text(encoding="utf-8")
    doc = ("<!doctype html>\n<html lang=\"zh-Hant-TW\">\n<head>\n<meta charset=\"utf-8\">\n"
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
           "<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}"
           "body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n"
           "</head>\n<body>\n" + frag + "\n</body>\n</html>\n")
    (SITE / "index.html").write_text(doc, encoding="utf-8")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="更新節令健康曆資料")
    ap.add_argument("--only", default="ncdr,cdc,climate,temp",
                    help="只更新這些來源（逗號分隔：ncdr,cdc,climate,temp），其他沿用上一版")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    SITE.mkdir(exist_ok=True)
    now = dt.datetime.now(TW)
    stamp = now.isoformat(timespec="minutes")
    old = {}
    if (SITE / "data.json").exists():
        try:
            old = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
        except Exception:
            old = {}
    # 各來源最後一次成功更新的時間；舊版 data.json 沒有這欄時用 generated 代替
    updated = dict(old.get("updated") or {k: old.get("generated") for k in ("ncdr", "cdc", "climate", "temp") if k in old})
    data = {"generated": stamp, "errors": []}
    for key, fn in (("ncdr", lambda: fetch_ncdr(now.date())), ("cdc", fetch_cdc), ("climate", fetch_cwa),
                    ("temp", fetch_temp)):
        if key not in only:
            if key in old:
                data[key] = old[key]
            continue
        try:
            data[key] = fn()
            updated[key] = stamp
            print(f"[ok] {key}")
        except Exception as e:  # 某個來源失敗時保留上一版資料
            data["errors"].append(f"{key}: {e}")
            if key in old:
                data[key] = old[key]
            print(f"[fail] {key}: {e}", file=sys.stderr)
    data["updated"] = updated
    (SITE / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    build_site()
    print(f"wrote {SITE / 'data.json'} and index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
