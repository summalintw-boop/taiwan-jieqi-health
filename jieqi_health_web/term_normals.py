"""計算各測站「每個節氣」的 1991–2020 平均最高／最低溫，輸出 site/term_normals.json

資料：Open-Meteo 歷史資料（ERA5 再分析，免金鑰）。每天依太陽視黃經判斷屬於哪個節氣，
再把 30 年同一節氣的日最高／最低溫平均。平年值只需計算一次，不必每天更新。
用法：python term_normals.py
"""
import datetime as dt
import json
import math
import time
import urllib.error
from pathlib import Path

from update_data import TEMP_POINTS, get  # 共用測站座標與 SSL 設定

HERE = Path(__file__).resolve().parent
URL = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
       "&start_date=1991-01-01&end_date=2020-12-31&daily=temperature_2m_max,temperature_2m_min&timezone=Asia%2FTaipei")
NAMES = ['春分','清明','穀雨','立夏','小滿','芒種','夏至','小暑','大暑','立秋','處暑','白露',
         '秋分','寒露','霜降','立冬','小雪','大雪','冬至','小寒','大寒','立春','雨水','驚蟄']
RAD = math.pi / 180


def sun_lon(jd: float) -> float:
    t = (jd - 2451545) / 36525
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = (357.52911 + 35999.05029 * t - 0.0001537 * t * t) * RAD
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m)
         + (0.019993 - 0.000101 * t) * math.sin(2 * m) + 0.000289 * math.sin(3 * m))
    om = (125.04 - 1934.136 * t) * RAD
    return (l0 + c - 0.00569 - 0.00478 * math.sin(om)) % 360


def term_of(day: dt.date) -> int:
    # 臺灣時間當天 23:59（= UTC 15:59），與網頁判斷方式一致
    ms = dt.datetime(day.year, day.month, day.day, 15, 59, tzinfo=dt.timezone.utc).timestamp() * 1000
    return int(sun_lon(ms / 86400000 + 2440587.5) // 15)


def main() -> None:
    out = {"source": "Open-Meteo Historical Weather API（ERA5），1991–2020",
           "note": "每個節氣的日最高、最低溫 30 年平均（°C）；模式再分析值，與氣象署測站平年值可能略有差異",
           "names": NAMES, "stations": {}}
    cache = HERE / "site" / "term_normals.json"
    if cache.exists():
        out["stations"] = json.loads(cache.read_text(encoding="utf-8")).get("stations", {})
    for name, (lat, lon) in TEMP_POINTS.items():
        if name in out["stations"]:
            continue
        for attempt in range(5):
            try:
                res = json.loads(get(URL.format(lat=lat, lon=lon), timeout=300).decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    raise
                print("rate limited, waiting 70 s"); time.sleep(70)
        else:
            raise RuntimeError("Open-Meteo 一直回 429，請稍後再執行")
        d = res["daily"]
        acc = [[0.0, 0.0, 0] for _ in range(24)]
        for t, mx, mn in zip(d["time"], d["temperature_2m_max"], d["temperature_2m_min"]):
            if mx is None or mn is None:
                continue
            i = term_of(dt.date.fromisoformat(t))
            acc[i][0] += mx; acc[i][1] += mn; acc[i][2] += 1
        out["stations"][name] = [[round(a[0] / a[2], 1), round(a[1] / a[2], 1)] for a in acc]
        print(name, "立冬", out["stations"][name][15], "小寒", out["stations"][name][19], "大暑", out["stations"][name][8])
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    (HERE / "site" / "term_normals.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print("wrote site/term_normals.json")


if __name__ == "__main__":
    main()
