"""檢查 risk_rules.py 與 page.html 的 JavaScript 規則是否算出一樣的結果

用法：
    python check_risk_parity.py        # 產生比對頁並印出路徑，用瀏覽器開啟

比對頁會直接從 page.html 抽出規則程式碼（「天文」到「繪製」之間），在瀏覽器裡算：
  1. site/data.json 的每一天 × 四個地區
  2. 一整年的合成天氣（各種天氣類型、季節、雨、溫度，部分日子沒有溫度）
再與本程式用 risk_rules.py 算的結果逐筆比較，頁面最上方顯示「一致」或列出差異。
本機沒有 Node.js 也能用。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import sys
import tempfile
from pathlib import Path

import risk_rules as rr

HERE = Path(__file__).resolve().parent

TYPES = ["東北風少雨", "東北風多雨", "偏北風", "寒流", "大陸冷氣團", "鋒面", "西南氣流", "西南風多雨", "偏南風",
         "太平洋高壓", "午後對流", "颱風", "偏東風", "冷高壓出海", "高壓迴流", "無雨"]
SEASONS = ["冬季", "春季", "梅雨季", "夏季", "秋季", ""]


def synthetic() -> dict:
    days, temp = [], {st: {} for st in ("臺北", "臺中", "高雄", "宜蘭", "花蓮")}
    d0 = dt.date(2027, 1, 1)
    for i in range(365):
        d = (d0 + dt.timedelta(days=i)).isoformat()
        days.append({"date": d, "kind": "fcst", "type": TYPES[(i * 7) % len(TYPES)], "season": SEASONS[(i * 5) % len(SEASONS)],
                     "rain": i % 3 == 0, "solar": ""})
        for j, st in enumerate(temp):
            if st == "臺中" and i % 4 == 1:
                continue  # 測沒有溫度資料的規則分支
            base = 17 + 10 * math.sin((i - 100) / 365 * 6.2832)
            mn = round(base + ((i * 13 + j * 7) % 17) / 2 - 5, 1)
            mx = round(mn + ((i * 11 + j * 5) % 25) / 2 + 1, 1)
            temp[st][d] = [mx, mn]
    return {"ncdr": {"days": days}, "temp": {"stations": temp}}


def py_results(data: dict) -> dict:
    days = [dict(x) for x in data["ncdr"]["days"]]
    rr.mark_turns(days)
    res = {}
    for d in days:
        res[d["date"]] = {"term": (lambda t: [t["name"], t["start"], t["day"]])(rr.term_at(d["date"])),
                          "r": {reg: [[x["k"], x["lv"], x["name"], x["why"], x["groups"], x["act"]] for x in rr.risks(d, reg, data)]
                                for reg in rr.REGIONS}}
    return res


FIXED = [0, 0.5, 1.5, 2.5, 16.5, 23.45, -0.3, -2.5, -3.5, 7.4999, 12.500000001, 1.005, 33.95]

JS = r"""
const SETS=__SETS__, FIX=__FIX__;
__RULES__
const tw2=jd=>{const t=tw(jd);return`${t.y}-${String(t.m).padStart(2,'0')}-${String(t.d).padStart(2,'0')}`;};
const diffs=[]; let n=0;
for(const [name,set] of Object.entries(SETS)){
  DATA=set.data; let s=0; DATA.ncdr.days.forEach((d,i)=>{const p=DATA.ncdr.days[i-1];d._turn=!!(p&&p.type!==d.type);});
  for(const d of DATA.ncdr.days){
    const tm=termAt(d.date), py=set.py[d.date];
    const jt=[T[tm.i].n,tw2(tm.st),Math.floor(tm.jd-tm.st)+1];
    n++; if(JSON.stringify(jt)!==JSON.stringify(py.term))diffs.push(`${name} ${d.date} 節氣 JS=${JSON.stringify(jt)} PY=${JSON.stringify(py.term)}`);
    for(const reg of ['北部','中部','南部','東部']){
      const j=risks(d,reg).map(x=>[x.k,x.lv,x.name,x.why,x.groups,x.act]);
      n++; if(JSON.stringify(j)!==JSON.stringify(py.r[reg]))diffs.push(`${name} ${d.date} ${reg}\nJS=${JSON.stringify(j)}\nPY=${JSON.stringify(py.r[reg])}`);
    }
  }
}
FIX.forEach(([x,s])=>{n++;if(x.toFixed(0)!==s)diffs.push(`toFixed(${x}) JS=${x.toFixed(0)} PY=${s}`);});
window.PARITY={checks:n,diffs:diffs.length};
document.getElementById('out').textContent=(diffs.length?`有 ${diffs.length} 筆不一致（共 ${n} 項）\n\n`+diffs.slice(0,50).join('\n\n'):`一致：${n} 項比對全部相同`);
"""


def main() -> int:
    page = (HERE / "page.html").read_text(encoding="utf-8")
    m = re.search(r"// ===== 天文.*?(?=// ===== 繪製)", page, flags=re.S)
    if not m:
        print("page.html 找不到「// ===== 天文」到「// ===== 繪製」的區段", file=sys.stderr)
        return 1
    real = json.loads((HERE / "site" / "data.json").read_text(encoding="utf-8"))
    real = {"ncdr": {"days": real["ncdr"]["days"]}, "temp": real.get("temp")}
    syn = synthetic()
    sets = {"data.json": {"data": real, "py": py_results(real)}, "合成一年": {"data": syn, "py": py_results(syn)}}
    js = (JS.replace("__SETS__", json.dumps(sets, ensure_ascii=False))
            .replace("__FIX__", json.dumps([[x, rr.js_fixed(x)] for x in FIXED]))
            .replace("__RULES__", "let DATA=null;\n" + m.group(0)))
    html = ("<!doctype html><meta charset='utf-8'><title>規則一致性比對</title>"
            "<pre id='out' style='white-space:pre-wrap;font:14px monospace'>計算中…</pre><script>" + js + "</script>")
    out = Path(tempfile.gettempdir()) / "jieqi_risk_parity.html"
    out.write_text(html, encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
