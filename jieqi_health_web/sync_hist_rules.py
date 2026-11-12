"""把疾管署歷史季節性分級寫進健康提醒規則，並做一致性檢查

用法：
  python sync_hist_rules.py           # 依 site/cdc_seasonal.json 更新 page.html 與 risk_rules.py 的 HIST 常數、年度表三列
  python sync_hist_rules.py --check   # 只檢查，不修改；不一致時結束代碼 1

分級來源（全國、全年齡）：
  類流感、腹瀉、腸病毒：取「全部年份」與「排除 2020–2022」兩種算法中較高的分級
    （防疫期間類流感、腸病毒異常偏低，只看全部年份會漏掉正常年份的高峰）
  COVID-19：只有 2022–2025 年，取全部年份分級
  分級：0 低於年平均、1 略高（≥1.00 倍）、2 明顯偏高（≥1.10 倍）、3 歷史高峰（≥1.25 倍）
  字串第 0 個字元＝春分（太陽黃經 0°），依序到驚蟄。
年度表（SEA）三列：每個月取「中點落在該月的節氣」中最高的分級。
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

from term_normals import NAMES, term_of

HERE = Path(__file__).resolve().parent
KEYS = ["ili", "covid", "diarrhea", "ev"]
# 年度表列名 → 資料
SEA_ROWS = {"類流感・呼吸道": "ili", "腸病毒": "ev", "腸胃道感染（腹瀉）": "diarrhea"}
OLD_SEA_NAMES = {"流感・新冠・呼吸道": "類流感・呼吸道", "腸胃道感染": "腸胃道感染（腹瀉）"}


def hist_levels() -> dict:
    d = json.loads((HERE / "site" / "cdc_seasonal.json").read_text(encoding="utf-8"))
    out = {}
    for k in KEYS:
        g = d["data"][k]["全國"]["all"]
        main = [t["lv"] for t in g["main"]]
        if g.get("sens") and k != "covid":
            main = [max(a, b["lv"]) for a, b in zip(main, g["sens"])]
        out[k] = "".join(str(x) for x in main)
    return out, d["generated"]


def mid_months(year=2026):
    days = [dt.date(year, 1, 1) + dt.timedelta(k) for k in range(365)]
    mm = {}
    for i in range(24):
        ds = [x for x in days if term_of(x) == i]
        mm[i] = ds[len(ds) // 2].month
    return mm


def sea_from(levels: str):
    mm = mid_months()
    return [max([int(levels[i]) for i in range(24) if mm[i] == m] or [0]) for m in range(1, 13)]


def js_block(H, gen):
    return ("// @@HIST_BEGIN（由 sync_hist_rules.py 產生，請勿手改）\n"
            f"// 疾管署健保門診歷史季節性分級（全國、全年齡，統計產生 {gen}）：0 低於年平均、1 略高、2 明顯偏高（≥1.10 倍）、3 歷史高峰（≥1.25 倍）\n"
            "// 字串第 0 字＝春分…第 23 字＝驚蟄；類流感、腹瀉、腸病毒取「全部年份」與「排除 2020–2022」較高者\n"
            "const HIST={" + ",".join(f"{k}:'{H[k]}'" for k in KEYS) + "};\n"
            "const histLv=(k,ymd)=>+HIST[k][termAt(ymd).i];\n"
            "// @@HIST_END")


def py_block(H, gen):
    return ("# @@HIST_BEGIN（由 sync_hist_rules.py 產生，請勿手改）\n"
            f"# 疾管署健保門診歷史季節性分級（全國、全年齡，統計產生 {gen}），與 page.html 的 HIST 相同\n"
            "HIST = {" + ", ".join(f'"{k}": "{H[k]}"' for k in KEYS) + "}\n\n\n"
            "def hist_lv(k: str, ymd: str) -> int:\n"
            "    return int(HIST[k][term_at(ymd)[\"index\"]])\n"
            "# @@HIST_END")


def replace_block(s, begin, end, new):
    i, j = s.index(begin), s.index(end) + len(end)
    return s[:i] + new + s[j:]


def main():
    check = "--check" in sys.argv
    H, gen = hist_levels()
    problems = []
    page = (HERE / "page.html").read_text(encoding="utf-8")
    rr = (HERE / "risk_rules.py").read_text(encoding="utf-8")

    # 1. HIST 常數
    m1 = re.search(r"const HIST=\{([^}]*)\}", page)
    m2 = re.search(r"HIST = \{([^}]*)\}", rr)
    js_h = dict(re.findall(r"(\w+):'(\d{24})'", m1.group(1))) if m1 else {}
    py_h = dict(re.findall(r'"(\w+)": "(\d{24})"', m2.group(1))) if m2 else {}
    for k in KEYS:
        if js_h.get(k) != H[k]:
            problems.append(f"page.html HIST.{k} 與統計不符：{js_h.get(k)} ≠ {H[k]}")
        if py_h.get(k) != H[k]:
            problems.append(f"risk_rules.py HIST[{k}] 與統計不符：{py_h.get(k)} ≠ {H[k]}")

    # 2. 年度表三列
    for name, k in SEA_ROWS.items():
        want = sea_from(H[k])
        m = re.search(r"\['" + re.escape(name) + r"',\[([\d,]+)\]\]", page)
        have = [int(x) for x in m.group(1).split(",")] if m else None
        if have != want:
            problems.append(f"年度表「{name}」與統計不符：{have} ≠ {want}")

    # 3. 不應再出現的舊月份規則
    for pat, msg in ((r"fluSeason=\[11,12,1,2\]", "page.html 仍用 11–2 月判定流感季"),
                     (r"f\.m>=4&&f\.m<=7", "page.html 仍用 4–7 月判定腸病毒")):
        if re.search(pat, page):
            problems.append(msg)
    for pat, msg in ((r"m in \(11, 12, 1, 2\)", "risk_rules.py 仍用 11–2 月判定流感季"),
                     (r"4 <= m <= 7", "risk_rules.py 仍用 4–7 月判定腸病毒")):
        if re.search(pat, rr):
            problems.append(msg)
    sh = (HERE / "parts" / "shared_ui.js").read_text(encoding="utf-8")
    if "[11,12,1,2].includes(f.m)" in sh:
        problems.append("shared_ui.js 原因說明仍用 11–2 月判定流感流行期")

    if check:
        print("HIST（統計）:", H)
        print("一致" if not problems else "不一致：\n- " + "\n- ".join(problems))
        sys.exit(1 if problems else 0)

    # 寫入
    if "// @@HIST_BEGIN" in page:
        page = replace_block(page, "// @@HIST_BEGIN", "// @@HIST_END", js_block(H, gen))
    else:
        anchor = "function risks(d,region){"
        page = page.replace(anchor, js_block(H, gen) + "\n" + anchor, 1)
    for old, new in OLD_SEA_NAMES.items():
        page = page.replace(f"['{old}',[", f"['{new}',[")
    for name, k in SEA_ROWS.items():
        want = ",".join(map(str, sea_from(H[k])))
        page, n = re.subn(r"\['" + re.escape(name) + r"',\[[\d,]+\]\]", f"['{name}',[{want}]]", page)
        assert n == 1, name
    (HERE / "page.html").write_text(page, encoding="utf-8")

    if "# @@HIST_BEGIN" in rr:
        rr = replace_block(rr, "# @@HIST_BEGIN", "# @@HIST_END", py_block(H, gen))
    else:
        anchor = "def risks(d: dict, region: str, data: dict) -> list:"
        rr = rr.replace(anchor, py_block(H, gen) + "\n\n\n" + anchor, 1)
    (HERE / "risk_rules.py").write_text(rr, encoding="utf-8")
    print("updated HIST:", H)
    for name, k in SEA_ROWS.items():
        print(name, sea_from(H[k]))


if __name__ == "__main__":
    main()
