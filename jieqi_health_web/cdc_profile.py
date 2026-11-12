"""疾管署健保門診及住院就診人次：資料品質初查（只讀取、不修改）。
用法：python cdc_profile.py   （讀 cdc_raw/*.csv，印出摘要）
"""
import csv
from collections import Counter, defaultdict
from pathlib import Path

RAW = Path(__file__).resolve().parent / "cdc_raw"
FILES = {"ili": "NHI_Influenza_like_illness.csv", "covid": "NHI_COVID-19.csv",
         "diarrhea": "NHI_Diarrhea.csv", "ev": "NHI_EnteroviralInfection.csv"}

for key, fn in FILES.items():
    rows = list(csv.reader((RAW / fn).open(encoding="utf-8-sig")))
    head, body = rows[0], rows[1:]
    print("=" * 70, "\n", key, fn, "欄位:", head, "列數:", len(body))
    bad = [r for r in body if len(r) != len(head)]
    kinds, ages, counties, codes = Counter(), Counter(), Counter(), defaultdict(set)
    yw = defaultdict(int)
    dup = Counter()
    nonint = 0
    neg = 0
    gt = 0
    for r in body:
        if len(r) != len(head):
            continue
        y, w, k, a, c = r[:5]
        kinds[k] += 1; ages[a] += 1; counties[c] += 1; codes[c].add(r[7] if len(r) > 7 else "")
        dup[(y, w, k, a, c)] += 1
        try:
            n, t = int(r[5]), int(r[6])
            if n < 0 or t < 0: neg += 1
            if n > t: gt += 1
        except ValueError:
            nonint += 1
        yw[(int(y), int(w))] += 1
    print("欄數不符:", len(bad), "非整數:", nonint, "負值:", neg, "疾病人次>總人次:", gt,
          "重複鍵:", sum(1 for v in dup.values() if v > 1))
    print("就診類別:", dict(kinds))
    print("年齡別:", dict(ages))
    print("縣市數:", len(counties), sorted(counties))
    multi = {c: v for c, v in codes.items() if len(v) > 1}
    print("同縣市多個代碼:", multi)
    years = sorted({y for y, _ in yw})
    for y in years:
        ws = sorted(w for yy, w in yw if yy == y)
        miss = [w for w in range(1, max(ws) + 1) if w not in ws]
        cnt = [yw[(y, w)] for w in ws]
        print(f"  {y}: 週 {min(ws)}–{max(ws)}（{len(ws)} 週）缺週 {miss} 每週列數 {min(cnt)}–{max(cnt)}")
    full = len(kinds) * len(ages) * len(counties)
    print("每週完整組合數（類別×年齡×縣市）:", full)
