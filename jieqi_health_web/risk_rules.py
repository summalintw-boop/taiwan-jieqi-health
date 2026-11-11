"""臺灣節令健康曆：每日健康風險規則（伺服器端版本）

這個檔是 page.html 裡 JavaScript `risks()`、`parseWx()`、`tempOf()` 與節氣計算的 Python 移植，
讓 GitHub Actions 不開瀏覽器也能算出每天的風險，供 site/today.json 與 LINE 推播使用。

**改 page.html 的規則時，這裡要一起改**，改完執行 `python check_risk_parity.py` 產生比對頁，
用瀏覽器開啟確認網頁與本檔結果完全一致。

只用 Python 標準函式庫。
"""
from __future__ import annotations

import datetime as dt
import math
import re
from decimal import Decimal, ROUND_HALF_UP

# ===== 天文：太陽視黃經（與 page.html 相同算式）=====
RAD = math.pi / 180


def sun_lon(jd: float) -> float:
    T = (jd - 2451545) / 36525
    L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T * T
    M = (357.52911 + 35999.05029 * T - 0.0001537 * T * T) * RAD
    C = ((1.914602 - 0.004817 * T - 0.000014 * T * T) * math.sin(M)
         + (0.019993 - 0.000101 * T) * math.sin(2 * M) + 0.000289 * math.sin(3 * M))
    om = (125.04 - 1934.136 * T) * RAD
    l = L0 + C - 0.00569 - 0.00478 * math.sin(om)
    return ((l % 360) + 360) % 360


def to_jd(ms: float) -> float:
    return ms / 86400000 + 2440587.5


def from_jd(jd: float) -> float:
    return (jd - 2440587.5) * 86400000


def _js_mod(a: float, b: float) -> float:  # JavaScript 的 % 保留被除數正負號
    return math.fmod(a, b)


def solve(t: float, g: float) -> float:
    jd = g
    for _ in range(8):
        d = _js_mod(t - sun_lon(jd) + 540, 360) - 180
        jd += d * 365.2422 / 360
    return jd


def tw(jd: float) -> dt.date:
    """儒略日 → 臺灣時間的日期"""
    return (dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=from_jd(jd) + 8 * 3600000)).date()


def ymd_jd(s: str) -> float:
    y, m, d = map(int, s.split("-"))
    ms = (dt.datetime(y, m, d, 15, 59) - dt.datetime(1970, 1, 1)).total_seconds() * 1000
    return to_jd(ms)


JQ_NAMES = ["春分", "清明", "穀雨", "立夏", "小滿", "芒種", "夏至", "小暑", "大暑", "立秋", "處暑", "白露",
            "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至", "小寒", "大寒", "立春", "雨水", "驚蟄"]


def term_at(ymd: str) -> dict:
    """該日所在節氣：名稱、開始日、第幾天、下一個節氣"""
    jd = ymd_jd(ymd)
    lon = sun_lon(jd)
    i = math.floor(lon / 15)
    st = solve(i * 15, jd - (lon - i * 15) * 365.2422 / 360)
    ni = (i + 1) % 24
    nst = solve(ni * 15, st + 15.2)
    return {"name": JQ_NAMES[i], "index": i, "start": tw(st).isoformat(), "day": math.floor(jd - st) + 1,
            "next": JQ_NAMES[ni], "nextStart": tw(nst).isoformat()}


# ===== JavaScript 的 Number.toFixed：兩個整數一樣近時取較大者 =====
def js_fixed(x: float, digits: int = 0) -> str:
    """與 JS 相同：負數先取絕對值捨入再加負號，例如 (-2.5).toFixed(0) 是 -3、(-0.3).toFixed(0) 是 -0；兩個整數一樣近時取絕對值較大者"""
    v = Decimal(abs(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return ("-" if x < 0 else "") + f"{v:.{digits}f}"


# ===== 天氣類型 → 健康風險 規則（與 page.html 相同）=====
G = {
    "old": "65 歲以上長者", "solo": "獨居長者", "cvd": "高血壓、心臟病、中風病史", "dm": "糖尿病", "ckd": "慢性腎病、洗腎",
    "copd": "COPD、氣喘", "baby": "嬰幼兒", "ltc": "長照機構住民", "unvax": "未接種疫苗者", "outdoor": "戶外工作者",
    "mob": "行動不便、失能者", "home": "街友", "vent": "使用居家呼吸器、製氧機者", "oldhouse": "老舊公寓住戶",
    "skin": "異位性皮膚炎", "imm": "免疫力低下者", "care": "照顧孫輩的長者", "preg": "孕婦",
    "allergy": "過敏性鼻炎、過敏體質", "urt": "曾有蕁麻疹者", "bed": "臥床、長期穿尿布者",
}
SHORT = {"cvd": "心血管", "resp": "呼吸道", "air": "空品", "wetcold": "濕冷", "co": "一氧化碳", "skin": "皮膚乾癢",
         "allergy": "過敏", "eczema": "濕疹", "heat": "熱傷害", "flood": "災後感染", "dengue": "登革熱", "typhoon": "颱風",
         "gi": "腸胃", "ev": "腸病毒", "calm": "平穩"}
LVN = ["", "需留意", "風險中", "風險高"]
STN = {"北部": ["臺北"], "中部": ["臺中"], "南部": ["高雄"], "東部": ["宜蘭", "花蓮"]}
REGIONS = list(STN)
# 地區加權：某些風險在特定地區較明顯
RW = {"air": {"中部": 1, "南部": 1, "東部": -1}, "wetcold": {"北部": 1, "東部": 1, "中部": -1, "南部": -1},
      "dengue": {"南部": 1, "北部": -1, "東部": -1}, "heat": {"中部": 0, "南部": 0}}


def _has(p: str, t: str) -> bool:
    return re.search(p, t) is not None


def parse_wx(d: dict) -> dict:
    season_s = d.get("season") or ""
    t = (d.get("type") or "") + " " + season_s
    m = int(d["date"][5:7])
    if _has("冬", season_s): season = "wi"
    elif _has("梅", season_s): season = "me"
    elif _has("春", season_s): season = "sp"
    elif _has("夏", season_s): season = "su"
    elif _has("秋", season_s): season = "au"
    else:
        season = ("wi" if m in (12, 1, 2) else "sp" if m in (3, 4) else "me" if m in (5, 6)
                  else "su" if m in (7, 8, 9) else "au")
    rain = bool(d.get("rain"))
    rg = re.search("北部|中部|南部|東部|東北部|西半部|迎風", t)
    return {
        "season": season, "m": m,
        "ne": _has("東北", t), "n": _has("偏北|北風|北方", t) and not _has("東北", t),
        "cold": _has("寒流|冷氣團|冷高壓|寒潮", t),
        "sw": _has("西南", t), "s": _has("偏南|南風", t) and not _has("西南", t),
        "e": _has("偏東|東風", t) and not _has("東北", t),
        "front": _has("鋒面", t), "ty": _has("颱", t), "high": _has("高壓|太平洋", t) and not _has("冷高壓", t),
        "conv": _has("對流|雷", t),
        "wet": rain or (_has("多雨|豪雨|大雨|降雨", t) and not _has("少雨", t)),
        "dry": _has("少雨|無雨|乾", t) or (not rain and not _has("雨", t)),
        "region": rg.group(0) if rg else "",
    }


def temp_of(data: dict, date: str, region: str) -> dict | None:
    """每日最高／最低溫（Open-Meteo），依地區取代表測站"""
    st = STN[region][0]
    s = ((data or {}).get("temp") or {}).get("stations", {}).get(st)
    if not s or not s.get(date):
        return None
    pd = (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()
    p = s.get(pd)
    mx, mn = s[date]
    return {"st": st, "mx": mx, "mn": mn, "rng": mx - mn, "dmn": (mn - p[1]) if p else 0}


def mark_turns(days: list) -> None:
    """標記天氣類型轉換（與 page.html 載入資料後的處理相同），供過敏規則使用"""
    for i, d in enumerate(days):
        p = days[i - 1] if i > 0 else None
        d["_turn"] = bool(p and p.get("type") != d.get("type"))


def risks(d: dict, region: str, data: dict) -> list:
    f = parse_wx(d)
    out: list = []
    cool = f["season"] in ("au", "wi", "sp")
    wintery = f["season"] == "wi" or f["m"] in (12, 1, 2)
    m = f["m"]

    def add(k, lv, name, why, groups, act):
        lv += (RW.get(k) or {}).get(region) or 0
        if lv >= 1:
            out.append({"k": k, "lv": min(3, lv), "name": name, "why": why, "groups": [G[g] for g in groups], "act": act})

    tp = temp_of(data, d["date"], region)
    cold10 = bool(tp and tp["mn"] <= 10)
    drop = bool(tp and tp["dmn"] <= -5)
    tt = (f"（{tp['st']}最低 {js_fixed(tp['mn'])}°C"
          + (f"，比前一天低 {js_fixed(-tp['dmn'])}°C" if tp["dmn"] <= -3 else "") + "）") if tp else ""
    cvd_on = (tp["mn"] <= 16 or drop or f["cold"]) if tp else ((f["ne"] or f["n"] or f["cold"]) and cool)
    if cvd_on:
        lv = 3 if (f["cold"] or cold10 or drop) else ((2 if (tp["mn"] <= 13 or wintery) else 1) if tp else (3 if wintery else 2))
        add("cvd", lv, "心血管・中風", "冷空氣使氣溫下降、日夜溫差加大" + tt + "，血管收縮、血壓上升；低溫效應會延遲數天，冷空氣過後一週仍要留意。",
            ["old", "cvd", "dm", "ckd", "solo"], "早晚與清晨出門保暖頭頸手腳；每天量血壓、依醫囑使用藥物；胸痛、單側無力、口齒不清立即打 119。")
    flu_season = m in (11, 12, 1, 2)
    if f["ne"] or f["n"] or f["cold"] or (f["wet"] and cool) or flu_season:
        add("resp", 3 if (wintery or f["cold"] or (tp and tp["mn"] <= 12)) else 2, "呼吸道感染",
            ("現在是流感流行期（約 11 月到隔年 2 月）；" if flu_season else "") + "涼冷天氣使人待在室內、門窗緊閉，流感、新冠、RSV 與肺炎鏈球菌容易傳播；長者重症比例最高。",
            ["old", "baby", "copd", "ltc", "unvax"], "接種流感、新冠、肺炎鏈球菌疫苗；有症狀戴口罩在家休息；呼吸困難、意識改變儘速就醫。")
    if (f["ne"] or f["n"]) and f["dry"] and cool:
        add("air", 1, "空氣品質・氣喘 COPD", "東北季風期間中南部位於背風側，風弱時 PM2.5 等汙染物累積；乾冷空氣也會刺激呼吸道。",
            ["copd", "cvd", "old", "baby"], "查看空品 AQI，超過 100 減少戶外活動並戴口罩；依醫囑使用藥物。")
    if f["ne"] and f["wet"]:
        add("wetcold", 2, "濕冷・跌倒", "迎風面持續降雨、濕冷，路面與浴室濕滑；濕冷也讓關節不適、活動量下降。",
            ["old", "mob", "solo"], "浴室加防滑墊與扶手，雨天外出穿防滑鞋；室內保持溫暖乾燥。")
    if f["cold"] or ((f["ne"] or f["n"]) and wintery) or (tp and tp["mn"] <= 12):
        add("co", 3 if (f["cold"] or (tp and tp["mn"] <= 8)) else 2, "一氧化碳中毒", "天冷門窗緊閉、熱水器裝在室內或加蓋陽台，燃燒不完全產生一氧化碳。",
            ["oldhouse", "solo", "old"], "熱水器裝在室外、洗澡時開窗；頭痛頭暈想吐立即開窗離開；不要燒炭取暖。")
    if f["dry"] and cool and (f["ne"] or f["n"] or f["cold"]):
        add("skin", 1, "皮膚乾癢・乾燥型濕疹", "空氣乾燥加上洗熱水澡，皮膚屏障受損；長者皮脂分泌少，小腿、背部容易乾裂發癢，抓破後可能感染。",
            ["old", "skin", "dm"], "洗澡水不超過 40°C、少用肥皂，洗完 3 分鐘內擦乳液；剪短指甲避免抓破；癢到影響睡眠或出現滲液就醫。")
    # 過敏性鼻炎・蕁麻疹：日夜溫差大、天氣類型轉換、轉季月份
    swing = (tp["rng"] >= 8) if tp else (cool and f["dry"] and (f["ne"] or f["n"]))
    turn = bool(d.get("_turn"))
    shoulder = m in (3, 4, 10, 11)
    if swing or turn or shoulder:
        add("allergy", 2 if (swing and (turn or shoulder or (tp and tp["rng"] >= 10))) else 1, "過敏性鼻炎・蕁麻疹",
            "日夜溫差大或天氣型態轉換時，鼻黏膜與皮膚對冷熱刺激敏感，容易打噴嚏、鼻塞，或出現冷熱引起的蕁麻疹。"
            + (f"{tp['st']}日夜溫差約 {js_fixed(tp['rng'])}°C。" if tp else "") + ("這天的天氣類型和前一天不同。" if turn else ""),
            ["allergy", "urt", "copd", "skin"], "早晚出門戴口罩、圍巾保暖口鼻；依醫囑使用藥物；蕁麻疹合併呼吸困難、嘴唇腫立即就醫。")
    # 濕疹・汗疹・黴菌：高溫高濕
    if f["season"] in ("su", "me") and (f["wet"] or f["s"] or f["sw"] or f["high"] or f["conv"] or f["season"] == "me"):
        add("eczema", 2 if (f["season"] == "me" or f["wet"]) else 1, "濕疹・汗疹・皮膚黴菌",
            "高溫潮濕讓汗水悶在皮膚皺摺處，容易長汗疹、濕疹，也利於黴菌（股癬、念珠菌）孳生；臥床與穿尿布的長者最常見。",
            ["bed", "dm", "old", "baby"], "衣物選透氣吸汗材質，汗濕就換；皮膚皺摺處保持乾爽；照顧臥床者每 2 小時翻身並檢查尿布區皮膚；紅疹擴大或化膿就醫。")
    heat_old = f["season"] in ("su", "me") and (f["high"] or f["s"] or f["conv"] or f["e"] or (f["sw"] and not f["wet"]) or (f["season"] == "su" and f["dry"]))
    if (tp["mx"] >= 30) if tp else heat_old:
        lv = (3 if tp["mx"] >= 34 else 2 if tp["mx"] >= 32 else 1) if tp else (3 if (f["high"] or f["season"] == "su") else 2)
        add("heat", lv, "熱傷害", "高溫潮濕使身體散熱困難" + (f"（{tp['st']}最高 {js_fixed(tp['mx'])}°C）" if tp else "") + "；長者體溫調節較差，在室內不開冷氣也可能中暑。",
            ["old", "solo", "cvd", "ckd", "outdoor", "baby"], "10–14 時避免戶外活動，少量多次喝水；室內開冷氣或電扇；體溫高、意識不清立即降溫並打 119。")
    if f["wet"] and (f["sw"] or f["front"] or f["ty"] or f["season"] in ("me", "su")):
        add("flood", 3 if f["ty"] else 2, "豪雨後感染", "豪雨淹水後，汙水與土壤散播鉤端螺旋體、類鼻疽菌；傷口接觸汙水易感染。",
            ["dm", "ckd", "imm", "outdoor"], "清理時穿雨鞋、戴手套口罩；有傷口避免接觸汙水，發燒就醫並告知接觸史。")
    if 6 <= m <= 11 and (f["wet"] or f["s"] or f["sw"] or f["season"] == "su"):
        add("dengue", 2 if 8 <= m <= 10 else 1, "登革熱", "雨後積水容器孳生病媒蚊，氣溫高時傳播快；長者與二次感染者重症風險較高。",
            ["old", "cvd", "dm"], "清除積水容器、穿淺色長袖、用防蚊液；出現腹痛、出血等警訊立即就醫。")
    if f["ty"]:
        add("typhoon", 3, "颱風外傷・停電", "強風豪雨造成外傷、停電與交通中斷，維生器材與洗腎、透析治療可能受影響。",
            ["vent", "ckd", "mob", "ltc"], "備妥 3 天份藥物、行動電源與備援電源；依通知提前撤離。")
    if f["season"] in ("me", "su"):
        add("gi", 2 if f["season"] == "su" else 1, "食物中毒・腸胃炎", "高溫潮濕利於細菌孳生，食物在室溫下放置過久易引起中毒。",
            ["ltc", "baby", "old"], "生熟食分開、剩菜盡快冷藏；腹瀉時補充水分電解質。")
    elif wintery or m == 11 or m == 3:
        add("gi", 1, "諾羅病毒", "冬季諾羅病毒流行，長照機構與學校容易群聚。", ["ltc", "baby", "old"],
            "貝類煮熟；如廁後用肥皂洗手（酒精效果有限）；嘔吐物用漂白水處理。")
    if 4 <= m <= 7:
        add("ev", 2 if 5 <= m <= 6 else 1, "腸病毒", "每年 5–6 月為高峰，祖父母照顧孫輩時容易互相傳染。", ["baby", "care", "preg"],
            "照顧嬰幼兒前後用肥皂洗手；孫輩有手足口症狀時避免共用餐具。")
    if not out:
        out.append({"k": "calm", "lv": 1, "name": "天氣平穩", "why": "這個天氣類型沒有明顯的健康風險訊號。", "groups": [G["old"]],
                    "act": "維持規律作息，依醫囑使用藥物。"})
    return sorted(out, key=lambda r: -r["lv"])  # 與 JS Array.sort 一樣是穩定排序
