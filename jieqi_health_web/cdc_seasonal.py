"""疾管署多年期週資料 → 24 節氣歷史季節性（第四版網站使用）

用法（在本資料夾執行，不要加 -I）：
  python cdc_seasonal.py --download   # 先重新下載四份 CSV 到 cdc_raw/
  python cdc_seasonal.py              # 用 cdc_raw/ 內現有檔案計算

輸出：
  site/cdc_seasonal.json            網頁用的節氣統計
  reports/資料品質檢查報告.md
  reports/24節氣歷史統計.md
  reports/規則檢核報告.md
  reports/term_occurrences.csv      每一次節氣（逐年）的分配結果，可逐筆核對

計算方式（也寫在報告與網頁上）：
  1. 只用「門診」列。全年齡＝所有年齡別（含「不詳」）相加；65 歲以上＝年齡別「65+」。
  2. 週次：資料未載明週的定義；2016–2025 年中只有 2020、2025 有第 53 週，與美國 CDC MMWR
     疫情週（週日到週六，第 1 週為當年天數 ≥4 天的那一週）一致，故採此定義。
  3. 每週人次平均分到該週 7 天，再依每天所屬節氣加總＝依「週與節氣的重疊天數」分配。
     節氣以太陽視黃經計算，以臺灣時間當天 23:59 判定（與網頁一致）。
  4. 只採用「每一天都有資料」的完整節氣；節令年＝立春到下一個立春前一天，24 個節氣都完整才納入。
  5. 每日平均人次＝該節氣分配到的人次 ÷ 節氣天數（各節氣 14–16 天，故用每日平均）。
     年度相對就診強度＝該節氣每日平均 ÷ 同一節令年全年每日平均（1.00＝與當年平均相同）。
     年度間變異＝各年相對強度的標準差、最小值、最大值，以及「高於當年平均」的年數。
"""
import argparse
import csv
import datetime as dt
import io
import json
import math
import statistics as stx
import urllib.request
from collections import defaultdict
from pathlib import Path

from term_normals import NAMES, term_of
from update_data import CDC_BASE, REGIONS, SSL_CTX, UA

HERE = Path(__file__).resolve().parent
RAW = HERE / "cdc_raw"
REP = HERE / "reports"
SETS = {
    "ili": ("NHI_Influenza_like_illness.csv", "類流感", "https://data.gov.tw/dataset/14593"),
    "covid": ("NHI_COVID-19.csv", "COVID-19", "https://data.gov.tw/dataset/177291"),
    "diarrhea": ("NHI_Diarrhea.csv", "腹瀉", "https://data.gov.tw/dataset/14597"),
    "ev": ("NHI_EnteroviralInfection.csv", "腸病毒", "https://data.gov.tw/dataset/14590"),
}
CASE_DEF = {
    "covid": "資料集說明：ICD-10 代碼 U07.1",
    "ili": "資料集說明未載明 ICD 代碼；本平台未查得官方代碼對照表",
    "diarrhea": "資料集說明未載明 ICD 代碼；本平台未查得官方代碼對照表",
    "ev": "資料集說明未載明 ICD 代碼；本平台未查得官方代碼對照表",
}
REG_ORDER = ["全國", "北部", "中部", "南部", "東部"]
AGES = {"all": "全年齡", "65+": "65 歲以上"}
LISCHUN = NAMES.index("立春")
# 顯示門檻（本平台自訂，非官方分級）：平均相對強度
TH = [(1.25, 3, "歷史高峰"), (1.10, 2, "明顯偏高"), (1.00, 1, "略高於年平均"), (0, 0, "低於年平均")]
PANDEMIC = {2020, 2021, 2022}
FEW = 10   # 平均每日人次低於此值：人次太少，相對強度不穩定，網頁不分級   # 敏感度分析排除的節令年（COVID-19 防疫措施期間）


def lv_of(ri):
    for th, lv, _ in TH:
        if ri >= th:
            return lv
    return 0


def mmwr_start(y: int) -> dt.date:
    j = dt.date(y, 1, 1)
    wd = (j.weekday() + 1) % 7  # 週日=0
    return j - dt.timedelta(wd) if wd <= 3 else j + dt.timedelta(7 - wd)


def download():
    RAW.mkdir(exist_ok=True)
    for fn, *_ in SETS.values():
        req = urllib.request.Request(CDC_BASE + fn, headers=UA)
        with urllib.request.urlopen(req, timeout=600, context=SSL_CTX) as r:
            (RAW / fn).write_bytes(r.read())
        print("downloaded", fn)


def county_region():
    m = {}
    for reg, cs in REGIONS.items():
        for c in cs:
            m[c] = reg
    return m


def load(key):
    fn = SETS[key][0]
    text = (RAW / fn).read_text(encoding="utf-8-sig")
    rd = csv.reader(io.StringIO(text))
    head = next(rd)
    rows = [r for r in rd]
    return head, rows


# ---------- 1. 資料品質 ----------
def quality(key, head, rows):
    c2r = county_region()
    q = {"key": key, "name": SETS[key][1], "file": SETS[key][0], "columns": head, "rows": len(rows)}
    bad_len = sum(1 for r in rows if len(r) != len(head))
    nonint = neg = gt = 0
    gt_samples = []
    kinds, ages, counties = defaultdict(int), defaultdict(int), defaultdict(int)
    yw_rows = defaultdict(int)
    opd_rows = defaultdict(int)
    keys = set()
    dup = 0
    for r in rows:
        if len(r) != len(head):
            continue
        y, w, k, a, c = r[:5]
        try:
            n, t = int(r[5]), int(r[6])
        except ValueError:
            nonint += 1
            continue
        if n < 0 or t < 0:
            neg += 1
        if n > t:
            gt += 1
            if len(gt_samples) < 5:
                gt_samples.append(f"{y} 年第 {w} 週 {k} {a} {c}：{n} > {t}")
        kk = (y, w, k, a, c)
        dup += kk in keys
        keys.add(kk)
        kinds[k] += 1; ages[a] += 1; counties[c] += 1
        yw_rows[(int(y), int(w))] += 1
        if k == "門診" and a != "不詳":
            opd_rows[(int(y), int(w))] += 1
    years = sorted({y for y, _ in yw_rows})
    per_year = []
    week53 = []
    for y in years:
        ws = sorted(w for yy, w in yw_rows if yy == y)
        miss = [w for w in range(1, max(ws) + 1) if w not in ws]
        per_year.append({"y": y, "w0": ws[0], "w1": ws[-1], "n": len(ws), "missing": miss})
        if max(ws) == 53:
            week53.append(y)
    full_opd = 8 * len(counties)
    incomplete_opd = {f"{y}-W{w:02d}": v for (y, w), v in sorted(opd_rows.items()) if v < full_opd}
    q.update(bad_len=bad_len, nonint=nonint, neg=neg, gt=gt, gt_samples=gt_samples, dup=dup,
             kinds=dict(kinds), ages=dict(ages), counties=sorted(counties),
             unmapped=[c for c in sorted(counties) if c not in c2r],
             per_year=per_year, week53=week53, full_opd=full_opd, incomplete_opd=incomplete_opd,
             first=f"{per_year[0]['y']} 年第 {per_year[0]['w0']} 週", last=f"{per_year[-1]['y']} 年第 {per_year[-1]['w1']} 週",
             last_yw=(per_year[-1]['y'], per_year[-1]['w1']))
    return q


# ---------- 2. 週 → 每日 ----------
def daily_series(rows):
    """回傳 {(region, age): {date: (人次, 總人次)}}（每週平均分到 7 天）"""
    c2r = county_region()
    wk = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in rows:
        if len(r) < 7 or r[2] != "門診":
            continue
        y, w, a, c = int(r[0]), int(r[1]), r[3], r[4]
        n, t = int(r[5]), int(r[6])
        for reg in ("全國", c2r.get(c)):
            if reg is None:
                continue
            for age in ("all", "65+"):
                if age == "65+" and a != "65+":
                    continue
                v = wk[(reg, age)][(y, w)]
                v[0] += n; v[1] += t
    out = {}
    for g, weeks in wk.items():
        d = {}
        for (y, w), (n, t) in weeks.items():
            s = mmwr_start(y) + dt.timedelta(7 * (w - 1))
            for i in range(7):
                d[s + dt.timedelta(i)] = (n / 7, t / 7)
        out[g] = d
    return out


def occurrences(d0: dt.date, d1: dt.date):
    """[(節氣 index, 起日, 迄日)]"""
    occ = []
    cur, start = term_of(d0), d0
    x = d0 + dt.timedelta(1)
    while x <= d1:
        t = term_of(x)
        if t != cur:
            occ.append((cur, start, x - dt.timedelta(1)))
            cur, start = t, x
        x += dt.timedelta(1)
    occ.append((cur, start, d1))
    return occ


def analyse(series, occ):
    """series: {date:(n,t)} → 每次節氣結果與節令年"""
    recs = []
    for i, a, b in occ:
        days = (b - a).days + 1
        vals = [series.get(a + dt.timedelta(k)) for k in range(days)]
        ok = all(v is not None for v in vals)
        n = sum(v[0] for v in vals if v) if ok else None
        t = sum(v[1] for v in vals if v) if ok else None
        recs.append({"i": i, "start": a, "end": b, "days": days, "ok": ok, "n": n, "t": t})
    cycles = []
    for k, r in enumerate(recs):
        if r["i"] == LISCHUN and k + 24 <= len(recs):
            grp = recs[k:k + 24]
            if [g["i"] for g in grp] == [(LISCHUN + j) % 24 for j in range(24)] and all(g["ok"] for g in grp):
                tot_n = sum(g["n"] for g in grp); tot_d = sum(g["days"] for g in grp)
                mean = tot_n / tot_d
                for g in grp:
                    g["cycle"] = r["start"].year
                    g["daily"] = g["n"] / g["days"]
                    g["ri"] = g["daily"] / mean if mean else None
                    g["share"] = g["n"] / g["t"] if g["t"] else None
                cycles.append({"y": r["start"].year, "mean": mean, "terms": grp})
    return recs, cycles


def summarise(cycles, exclude=frozenset()):
    cyc = [c for c in cycles if c["y"] not in exclude]
    out = []
    for i in range(24):
        gs = [g for c in cyc for g in c["terms"] if g["i"] == i]
        if not gs:
            out.append(None); continue
        ri = [g["ri"] for g in gs]
        daily = [g["daily"] for g in gs]
        share = [g["share"] for g in gs if g["share"] is not None]
        peak = sum(1 for c in cyc if max(c["terms"], key=lambda g: g["ri"])["i"] == i)
        out.append({
            "i": i, "n": len(gs),
            "daily": round(stx.mean(daily), 1), "daily_sd": round(stx.stdev(daily), 1) if len(daily) > 1 else None,
            "ri": round(stx.mean(ri), 3), "ri_sd": round(stx.stdev(ri), 3) if len(ri) > 1 else None,
            "ri_min": round(min(ri), 3), "ri_max": round(max(ri), 3),
            "ri_med": round(stx.median(ri), 3),
            "above": sum(1 for v in ri if v >= 1), "peak": peak,
            # 年度一致性：≥70% 的年份同在年平均以上（或以下）才算「穩定」
            "stable": max(sum(1 for v in ri if v >= 1), sum(1 for v in ri if v < 1)) / len(ri) >= 0.7,
            "share": round(stx.mean(share) * 100, 3) if share else None,
            "lv": lv_of(stx.mean(ri)),
            "by_year": [round(g["ri"], 2) for g in gs],
        })
    return {"cycles": [c["y"] for c in cyc], "terms": out}


# ---------- 3. 原本的人工規則 ----------
def manual_rules():
    import re
    src = (HERE / "page.html").read_text(encoding="utf-8")
    sea_block = src[src.index("const SEA=["):src.index("const STN=")]
    sea = {m.group(1): [int(x) for x in m.group(2).split(",")]
           for m in re.finditer(r"\['([^']+)',\[([\d,]+)\]\]", sea_block)}
    t_block = src[src.index("const T=["):src.index("const SEA=[")]
    tnotes = {}
    for m in re.finditer(r"\['([^']{2})',S\.\w+,'[^']*',\[([^\]]*)\]", t_block):
        tnotes[m.group(1)] = re.findall(r"'([^']*)'", m.group(2))
    return sea, tnotes


def mid_month(i, year=2026):
    """節氣中點所在月份（與第三版網頁換算方式相同）"""
    d = dt.date(year, 1, 1)
    days = [d + dt.timedelta(k) for k in range(366) if (d + dt.timedelta(k)).year == year]
    ds = [x for x in days if term_of(x) == i]
    return ds[len(ds) // 2].month


def spearman(a, b):
    def rank(v):
        idx = sorted(range(len(v)), key=lambda k: v[k])
        r = [0.0] * len(v)
        k = 0
        while k < len(v):
            j = k
            while j + 1 < len(v) and v[idx[j + 1]] == v[idx[k]]:
                j += 1
            for m in range(k, j + 1):
                r[idx[m]] = (k + j) / 2
            k = j + 1
        return r
    ra, rb = rank(a), rank(b)
    ma, mb = stx.mean(ra), stx.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else float("nan")


# ---------- 主程式 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args()
    if args.download:
        download()
    REP.mkdir(exist_ok=True)
    fetched = {k: dt.datetime.fromtimestamp((RAW / v[0]).stat().st_mtime).strftime("%Y-%m-%d %H:%M")
               for k, v in SETS.items()}
    Q, R = {}, {}
    occ_rows = []
    for key in SETS:
        head, rows = load(key)
        q = Q[key] = quality(key, head, rows)
        ser = daily_series(rows)
        all_days = sorted(ser[("全國", "all")])
        occ = occurrences(all_days[0], all_days[-1])
        R[key] = {}
        for reg in REG_ORDER:
            R[key][reg] = {}
            for age in AGES:
                recs, cycles = analyse(ser[(reg, age)], occ)
                main_s = summarise(cycles)
                sens = summarise(cycles, PANDEMIC) if key != "covid" else None
                md = round(stx.mean(c["mean"] for c in cycles), 1)
                R[key][reg][age] = {"main": main_s, "sens": sens, "mean_daily": md, "few": md < FEW}
                for c in cycles:
                    for g in c["terms"]:
                        occ_rows.append([SETS[key][1], reg, AGES[age], c["y"], NAMES[g["i"]], g["start"], g["end"],
                                         g["days"], round(g["n"], 1), round(g["daily"], 1), round(g["ri"], 3),
                                         round(g["share"] * 100, 3) if g["share"] else ""])
        print(key, "cycles:", R[key]["全國"]["all"]["main"]["cycles"])

    # 網頁 JSON
    web = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "names": NAMES,
        "method": ("只用健保門診人次。每週人次平均分到 7 天，依每天所屬節氣加總（週與節氣重疊天數分配）。"
                   "節令年為立春到下一個立春前一天，24 個節氣資料都完整才納入。"
                   "相對強度＝該節氣每日平均人次 ÷ 同一節令年全年每日平均。"),
        "thresholds": [{"min": th, "lv": lv, "label": lab} for th, lv, lab in TH],
        "pandemic_excluded": sorted(PANDEMIC),
        "sets": {k: {"name": SETS[k][1], "dataset": SETS[k][2], "csv": CDC_BASE + SETS[k][0],
                     "first": Q[k]["first"], "last": Q[k]["last"], "fetched": fetched[k],
                     "case_def": CASE_DEF[k], "cycles": R[k]["全國"]["all"]["main"]["cycles"]} for k in SETS},
        "few_threshold": FEW,
        "data": {k: {reg: {age: {"main": v["main"]["terms"], "sens": v["sens"]["terms"] if v["sens"] else None,
                                 "mean_daily": v["mean_daily"], "few": v["few"],
                                 "sens_cycles": v["sens"]["cycles"] if v["sens"] else None}
                           for age, v in regs.items()} for reg, regs in R[k].items()} for k in SETS},
    }
    (HERE / "site" / "cdc_seasonal.json").write_text(json.dumps(web, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    with (REP / "term_occurrences.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["疾病", "地區", "年齡", "節令年", "節氣", "起日", "迄日", "天數", "分配人次", "每日平均", "相對強度", "占健保門診總人次%"])
        w.writerows(occ_rows)

    write_quality(Q, fetched)
    write_stats(R, Q)
    write_rules(R)
    print("done")


def fmt_pct(x):
    return f"{x:.2f}"


def write_quality(Q, fetched):
    L = ["# 疾管署健保門診及住院就診人次：資料品質檢查報告", "",
         f"產生時間：{dt.datetime.now():%Y-%m-%d %H:%M}（程式：cdc_seasonal.py）", "",
         "## 檢查項目與結果", ""]
    for k, q in Q.items():
        L += [f"### {q['name']}（{q['file']}）", "",
              f"- 資料集頁面：{SETS[k][2]}；檔案下載時間：{fetched[k]}",
              f"- 欄位：{'、'.join(q['columns'])}；共 {q['rows']:,} 列",
              f"- 年度範圍：{q['first']} 到 {q['last']}",
              f"- 病例定義：{CASE_DEF[k]}",
              "- 統計單位：健保就診「人次」（同一人多次就診會重複計算），不是病例數或人數；分子為該疾病就診人次，"
              "「健保就診總人次」為同縣市、同年齡別、同就診類別的全部健保就診人次。",
              f"- 就診類別：{'、'.join(f'{a} {b:,} 列' for a, b in q['kinds'].items())}",
              f"- 年齡分組：{'、'.join(q['ages'])}（有「65+」，可以分析 65 歲以上；「不詳」只計入全年齡）",
              f"- 縣市：{len(q['counties'])} 個。未對應到北中南東地區、只計入全國的縣市：{'、'.join(q['unmapped']) or '無'}",
              f"- 欄數不符 {q['bad_len']} 列；非整數 {q['nonint']} 列；負值 {q['neg']} 列；重複鍵 {q['dup']} 列",
              f"- 疾病人次大於健保就診總人次：{q['gt']} 列" + (f"（例：{'；'.join(q['gt_samples'])}）" if q['gt'] else ""),
              f"- 有第 53 週的年份：{'、'.join(map(str, q['week53'])) or '無'}",
              ]
        miss = [f"{p['y']} 年缺第 {','.join(map(str, p['missing']))} 週" for p in q['per_year'] if p['missing']]
        L.append("- 年度內缺週：" + ("；".join(miss) if miss else "無（各年度第 1 週到最後一週連續）"))
        first = q["per_year"][0]
        if first["w0"] != 1:
            L.append(f"- 資料起點：{first['y']} 年從第 {first['w0']} 週開始，之前沒有資料（不是缺漏，是資料集開始時間）。")
        inc = q["incomplete_opd"]
        L.append(f"- 門診列完整度：每週應有 8 個年齡組 × {len(q['counties'])} 縣市 = {q['full_opd']} 列；"
                 + (f"少於此數的週：{'、'.join(f'{a}（{b} 列）' for a, b in list(inc.items())[:10])}" if inc else "每週都完整"))
        L.append("")
    L += ["## 共通事項與限制", "",
          "1. **週的定義**：資料集未說明。2016–2025 年只有 2020、2025 年有第 53 週，與美國 CDC MMWR 疫情週（週日到週六，"
          "第 1 週為該年有 4 天以上的那一週）一致；ISO 週（週一起算）的 53 週年份是 2020、2026，不一致。本平台採 MMWR 定義，屬推定。",
          "2. **未出現的組合**：資料中有大量人次為 0 的列，表示 0 會被列出；門診（排除「不詳」）幾乎每週都有完整 176 列。"
          "住院列較少，推測是當週該組合沒有任何健保住院；本分析只用門診，不受影響。",
          "3. **COVID-19 疾病人次大於總人次**：集中在 2022 年住院列，原因資料集未說明（可能分子分母歸戶方式不同）。"
          "本分析只用門診與人次加總，不使用該比例做分級；這些列照原值保留。",
          "4. **病例定義**：只有 COVID-19 資料集載明 ICD-10 U07.1。類流感、腹瀉、腸病毒資料集頁面沒有寫 ICD 代碼，"
          "本平台沒有查到官方對照表，不自行推測；若代碼歷年有調整，會影響長期比較。",
          "5. **最新週**：資料每天或每週更新，最近幾週數字之後可能被補登修正；最近 16 週在網站上分開顯示，不納入歷史基準"
          "（歷史基準只用完整節令年）。",
          "6. **門診量本身受假日影響**：農曆春節（落在大寒、立春或雨水，年年不同）診所休診，人次下降；報告另列"
          "「占健保門診總人次比例」供對照。",
          ""]
    (REP / "資料品質檢查報告.md").write_text("\n".join(L), encoding="utf-8")


def write_stats(R, Q):
    L = ["# 24 節氣歷史就診統計（疾管署健保門診人次）", "",
         f"產生時間：{dt.datetime.now():%Y-%m-%d %H:%M}（程式：cdc_seasonal.py；逐筆明細：term_occurrences.csv）", "",
         "## 計算方式", "",
         "- 只用「門診」人次。全年齡＝所有年齡別相加（含「不詳」）；65 歲以上＝年齡別「65+」。",
         "- 每週人次平均分到該週 7 天，再依每天所屬節氣加總，等於依週與節氣的重疊天數比例分配。",
         "- 節令年：立春到下一個立春前一天；24 個節氣每天都有資料才納入。",
         "- 每日平均人次＝分配人次 ÷ 節氣天數。相對強度＝每日平均 ÷ 同節令年全年每日平均。",
         "- 年度間變異：相對強度的標準差、最小、最大，以及「高於當年平均」的年數。",
         "- 年度一致：至少 70% 的年份同在當年平均以上（或同在以下）為「是」；否則表示各年方向不同，平均值容易被少數大流行年拉高。",
         f"- 網頁顯示分級（本平台自訂、非官方）：平均相對強度 ≥1.25 歷史高峰；1.10–1.25 明顯偏高；1.00–1.10 略高於年平均；<1.00 低於年平均。",
         f"- 敏感度分析：類流感、腹瀉、腸病毒另算排除 2020–2022 節令年（防疫措施期間）的結果。",
         "- **這是過去的群體就診量，不代表未來或個人的發病風險。**", ""]
    for k in SETS:
        for age in AGES:
            m = R[k]["全國"][age]["main"]; s = R[k]["全國"][age]["sens"]
            L += [f"## {SETS[k][1]}・全國・{AGES[age]}", "",
                  (f"> **人次太少**：平均每日只有 {R[k]['全國'][age]['mean_daily']} 人次（低於 {FEW}），相對強度容易受少數就診影響，網頁不分級，下表僅供參考。\n\n"
                   if R[k]['全國'][age]['few'] else "") +
                  f"納入節令年：{'、'.join(map(str, m['cycles']))}（{len(m['cycles'])} 年）" +
                  (f"；敏感度分析（排除 2020–2022）：{'、'.join(map(str, s['cycles']))}" if s else ""), "",
                  "| 節氣 | 每日平均人次（SD） | 相對強度 平均 | 中位數 | SD | 最小–最大 | 高於年平均年數 | 年度一致 | 當年最高峰次數 | 占門診總人次% | 分級 |" +
                  (" 排除2020–22 相對強度 |" if s else ""),
                  "|---|---|---|---|---|---|---|---|---|---|---|" + ("---|" if s else "")]
            order = [(LISCHUN + j) % 24 for j in range(24)]
            for i in order:
                t = m["terms"][i]
                lab = next(l for th, lv, l in TH if lv == t["lv"])
                row = (f"| {NAMES[i]} | {t['daily']:,.0f}（{t['daily_sd']:,.0f}） | {t['ri']:.2f} | {t['ri_med']:.2f} | {t['ri_sd']:.2f} | "
                       f"{t['ri_min']:.2f}–{t['ri_max']:.2f} | {t['above']}/{t['n']} | {'是' if t['stable'] else '否'} | {t['peak']} | {t['share']:.2f} | {lab} |")
                if s:
                    row += f" {s['terms'][i]['ri']:.2f} |"
                L.append(row)
            L.append("")
    L += ["## 不確定性說明", "",
          "- 年數少：類流感、腹瀉、腸病毒 10 個節令年；COVID-19 只有 4 個節令年（2022 年立春到 4 月本土病例極少，相對強度接近 0），"
          "高峰由個別疫情波決定（2022–2025 多在小滿到小暑），還不能視為穩定的季節性，網頁上另外標示。",
          "- 腸病毒呈雙峰（夏至前後、秋末到冬初），且 2020–2022 年型態異常（例如 2021 年上半年偏高、2022 年冬季偏高），各節氣的年度一致性偏低。",
          "- 2020–2022 年防疫措施使類流感、腸病毒等大幅下降，影響平均；請對照敏感度分析欄。",
          "- 週內平均分配假設每天就診量相同，實際上週末、連假較少，節氣交界的週會有些許誤差。",
          "- 農曆春節日期每年不同，會讓大寒、立春、雨水的門診量偏低；可參考「占門診總人次%」。",
          "- 地區（北中南東）結果在 site/cdc_seasonal.json 與 term_occurrences.csv，東部人數少、變異較大。",
          f"- 平均每日人次低於 {FEW} 的組合（例如腸病毒 65 歲以上，各地區與全國都是）視為人次太少，網頁上不顯示分級。", ""]
    (REP / "24節氣歷史統計.md").write_text("\n".join(L), encoding="utf-8")


def write_rules(R):
    sea, tnotes = manual_rules()
    mm = {i: mid_month(i) for i in range(24)}
    order = [(LISCHUN + j) % 24 for j in range(24)]
    L = ["# 規則檢核報告：原本人工月份規則 vs 疾管署歷史節氣季節性", "",
         f"產生時間：{dt.datetime.now():%Y-%m-%d %H:%M}（程式：cdc_seasonal.py）", "",
         "比較基準：全國、全年齡、所有納入節令年的平均相對強度（≥1.00＝高於當年平均；≥1.10＝明顯偏高）。",
         "人工規則的月份依「節氣中點所在月份」換算成節氣（與第三版網頁年度表相同）。", "",
         "判定：**一致**＝人工規則標示的節氣與歷史偏高節氣大致相同；**部分一致**＝高峰方向對但範圍不同；"
         "**不一致**＝人工規則標示的時段在歷史資料中低於年平均，或漏掉歷史高峰。", ""]

    def ri(k, i, age="all"):
        return R[k]["全國"][age]["main"]["terms"][i]["ri"]

    def compare(title, k, flagged, note):
        hi = [i for i in order if ri(k, i) >= 1.10]
        above = [i for i in order if ri(k, i) >= 1.0]
        fl = [i for i in order if flagged(i)]
        tp = [i for i in fl if ri(k, i) >= 1.0]
        fp = [i for i in fl if ri(k, i) < 1.0]
        miss = [i for i in hi if i not in fl]
        if not fp and not miss:
            verdict = "一致"
        elif len(tp) >= len(fp) and len(miss) <= 2:
            verdict = "部分一致"
        else:
            verdict = "不一致"
        L.extend([f"### {title}", "", f"- 人工規則：{note}",
                  f"- 規則標示的節氣（{len(fl)} 個）：{'、'.join(NAMES[i] for i in fl) or '無'}",
                  f"- 歷史高於年平均（≥1.00）的節氣（{len(above)} 個）：{'、'.join(NAMES[i] for i in above)}",
                  f"- 歷史明顯偏高（≥1.10）的節氣：{'、'.join(f'{NAMES[i]} {ri(k, i):.2f}' for i in hi) or '無'}",
                  f"- 規則標示但歷史低於年平均：{'、'.join(f'{NAMES[i]} {ri(k, i):.2f}' for i in fp) or '無'}",
                  f"- 歷史明顯偏高但規則未標示：{'、'.join(f'{NAMES[i]} {ri(k, i):.2f}' for i in miss) or '無'}",
                  f"- **判定：{verdict}**", ""])
        return verdict

    summary = []
    L += ["## A. 日曆每日提醒的月份規則（risks 函式）", ""]
    v = compare("呼吸道感染：流感季（類流感）", "ili", lambda i: mm[i] in (11, 12, 1, 2),
                "11 月到隔年 2 月視為流感流行期，每天都標「呼吸道感染」（另有寒流、東北季風等天氣條件）")
    summary.append(("呼吸道感染（流感季 11–2 月）", "類流感", v))
    v = compare("呼吸道感染：流感季（COVID-19）", "covid", lambda i: mm[i] in (11, 12, 1, 2),
                "同上；呼吸道提醒文字包含新冠")
    summary.append(("呼吸道感染（流感季 11–2 月）", "COVID-19", v))
    v = compare("腸病毒", "ev", lambda i: 4 <= mm[i] <= 7, "4–7 月提醒腸病毒，5–6 月提高一級")
    summary.append(("腸病毒（4–7 月）", "腸病毒", v))
    v = compare("腸胃：食物中毒與諾羅病毒", "diarrhea",
                lambda i: mm[i] in (5, 6, 7, 8, 9, 11, 12, 1, 2, 3),
                "NCDR 季節為梅雨或夏季時提醒食物中毒・腸胃炎；冬季型天氣或 11、3 月提醒諾羅病毒。"
                "（梅雨季、夏季依 NCDR 季節標示，此處以約 5–9 月近似；冬季以 12–2 月近似）")
    summary.append(("腸胃（梅雨夏季＋冬季諾羅）", "腹瀉", v))
    if ri("diarrhea", 0) is not None:
        L.append("> 腸胃規則一年中約 10 個月都會觸發，幾乎無法區分季節；建議依下表歷史高峰收斂。\n")

    L += ["## B. 年度表人工等級（SEA，每月 0–3 級）", "",
          "以 Spearman 等級相關比較 24 節氣的人工等級與歷史平均相對強度（1＝完全同向，0＝無關，負值＝反向）。", ""]
    pairs = [("流感・新冠・呼吸道", "ili"), ("流感・新冠・呼吸道", "covid"), ("腸病毒", "ev"), ("腸胃道感染", "diarrhea")]
    lvn = ["無", "低", "中", "高"]
    for row, k in pairs:
        if row not in sea:
            L.append(f"- 找不到人工列「{row}」"); continue
        man = [sea[row][mm[i] - 1] for i in order]
        his = [ri(k, i) for i in order]
        rho = spearman(man, his)
        dis = [f"{NAMES[i]}（人工{lvn[sea[row][mm[i] - 1]]}，歷史 {ri(k, i):.2f}）" for i in order
               if (sea[row][mm[i] - 1] >= 2 and ri(k, i) < 1.0) or (sea[row][mm[i] - 1] <= 1 and ri(k, i) >= 1.10)]
        verdict = "一致" if rho >= 0.7 and len(dis) <= 2 else ("部分一致" if rho >= 0.4 else "不一致")
        summary.append((f"年度表「{row}」", SETS[k][1], verdict))
        L += [f"### 「{row}」 vs {SETS[k][1]}", "",
              "| 節氣 | " + " | ".join(NAMES[i] for i in order) + " |",
              "|---|" + "---|" * 24,
              "| 人工等級 | " + " | ".join(lvn[x] for x in man) + " |",
              "| 歷史相對強度 | " + " | ".join(f"{x:.2f}" for x in his) + " |", "",
              f"- Spearman 相關：{rho:.2f}",
              f"- 明顯不一致的節氣：{'、'.join(dis) or '無'}",
              f"- **判定：{verdict}**", ""]

    L += ["## C. 節氣說明文字中的疾病敘述", "",
          "節氣卡片「常見健康問題」中提到這四類疾病的句子，對照該節氣的歷史相對強度。", "",
          "| 節氣 | 文字敘述 | 對應資料 | 歷史相對強度 | 判定 |", "|---|---|---|---|---|"]
    kw = [("腸病毒", "ev"), ("流感", "ili"), ("類流感", "ili"), ("新冠", "covid"), ("COVID", "covid"),
          ("諾羅", "diarrhea"), ("腹瀉", "diarrhea"), ("腸胃", "diarrhea"), ("食物中毒", "diarrhea")]
    for i in order:
        for s in tnotes.get(NAMES[i], []):
            hit = {k for w, k in kw if w in s}
            for k in sorted(hit):
                r = ri(k, i)
                rising = any(w in s for w in ("開始上升", "升溫", "上升"))
                if rising:
                    prev = ri(k, (i - 1) % 24)
                    ok = "一致" if r > prev else ("持平" if abs(r - prev) < 0.03 else "不一致")
                    why = f"前一節氣 {prev:.2f} → 本節氣 {r:.2f}"
                else:
                    ok = "一致" if r >= 1.0 else ("接近年平均" if r >= 0.95 else "不一致")
                    why = f"{r:.2f}"
                L.append(f"| {NAMES[i]} | {s} | {SETS[k][1]} | {why} | {ok} |")
                summary.append((f"節氣文字：{NAMES[i]}「{s}」", SETS[k][1], ok))
    L += ["", "## 總表", "", "| 規則 | 對照資料 | 判定 |", "|---|---|---|"]
    L += [f"| {a} | {b} | {c} |" for a, b, c in summary]
    L += ["", "## 限制", "",
          "- 只能檢核有疾管署對應資料的四類（類流感、COVID-19、腹瀉、腸病毒）。心血管、熱傷害、一氧化碳、過敏、"
          "濕疹、登革熱等規則沒有對應的週資料，本報告不做判定。",
          "- 日曆的每日提醒還受天氣類型與溫度影響，本報告只檢核其中與月份有關的部分。",
          "- 歷史就診季節性代表群體就診量，不代表個人風險；規則調整仍需公衛及醫療專家審閱。", ""]
    (REP / "規則檢核報告.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
