"""臺灣節令健康曆：今日摘要 site/today.json 與 LINE 每日推播訊息

用法：
    python line_daily.py                  # 由 site/data.json 產生 site/today.json，並印出四個地區的訊息（不推播）
    python line_daily.py --region 北部     # 只印北部
    python line_daily.py --send           # 有 LINE_CHANNEL_ACCESS_TOKEN 時才實際推播；沒有就只印出訊息

推播設定（環境變數，在 GitHub 放 Secrets / Variables）：
    LINE_CHANNEL_ACCESS_TOKEN  Messaging API 的 Channel access token（必要，Secret）
    LINE_MODE                  push（預設，只送給 LINE_TO）或 broadcast（送給官方帳號全部好友）
    LINE_TO                    push 模式的收件者 userId，多個用逗號分隔（最多 500 個）
    LINE_REGION                要推播哪一區的訊息：北部（預設）、中部、南部、東部

只用 Python 標準函式庫。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import risk_rules as rr

HERE = Path(__file__).resolve().parent
SITE = HERE / "site"
TW = dt.timezone(dt.timedelta(hours=8))
WD = "日一二三四五六"
SITE_URL = "https://summalintw-boop.github.io/taiwan-jieqi-health/"
KIND = {"obs": "已判識", "today": "今日推估", "fcst": "未來推估"}
LINE_API = "https://api.line.me/v2/bot/message/"


def review_note() -> str:
    """沿用 page.html 的 SITE.review（例如「草稿：內容待公共衛生及醫療專家審閱」）"""
    try:
        m = re.search(r"review\s*:\s*'([^']*)'", (HERE / "page.html").read_text(encoding="utf-8"))
        return m.group(1) if m else ""
    except OSError:
        return ""


def _age_days(stamp: str | None, now: dt.datetime) -> float:
    if not stamp:
        return float("inf")
    try:
        return (now - dt.datetime.fromisoformat(stamp)).total_seconds() / 86400
    except ValueError:
        return float("inf")


def build_today(data: dict, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(TW)
    ymd = now.date().isoformat()
    days = [dict(d) for d in ((data.get("ncdr") or {}).get("days") or [])]
    rr.mark_turns(days)
    d = next((x for x in days if x.get("date") == ymd), None)
    up = data.get("updated") or {}
    notes = []
    if d is None:
        notes.append("NCDR 日曆沒有今天的天氣類型，以下只依氣溫與月份判斷")
        wx = {"date": ymd, "type": "", "season": "", "rain": False}
    else:
        wx = d
    if _age_days(up.get("ncdr"), now) > 2:
        notes.append("NCDR 天氣日曆超過 2 天沒有更新")
    if _age_days(up.get("temp"), now) > 2:
        notes.append("預報溫度超過 2 天沒有更新")

    out = {
        "generated": now.isoformat(timespec="minutes"),
        "date": ymd,
        "weekday": WD[(now.date().weekday() + 1) % 7],
        "term": rr.term_at(ymd),
        "weather": None if d is None else {"season": d.get("season", ""), "type": d.get("type", ""),
                                           "rain": bool(d.get("rain")), "kind": KIND.get(d.get("kind"), d.get("kind")),
                                           "turn": bool(d.get("_turn"))},
        "notes": notes,
        "sources": {"weather": (data.get("ncdr") or {}).get("source"), "temp": (data.get("temp") or {}).get("source"),
                    "tempNote": (data.get("temp") or {}).get("note")},
        "updated": up,
        "review": review_note(),
        "site": SITE_URL,
        "levels": rr.LVN,
        "regions": {},
    }
    for reg in rr.REGIONS:
        tp = rr.temp_of(data, ymd, reg)
        rs = rr.risks(wx, reg, data)
        out["regions"][reg] = {
            "station": tp["st"] if tp else rr.STN[reg][0],
            "tmin": tp["mn"] if tp else None,
            "tmax": tp["mx"] if tp else None,
            "risks": [{"k": r["k"], "lv": r["lv"], "level": rr.LVN[r["lv"]], "name": r["name"],
                       "groups": r["groups"], "why": r["why"], "act": r["act"]} for r in rs],
        }
        out["regions"][reg]["message"] = format_message(out, reg)
    return out


def format_message(t: dict, reg: str) -> str:
    """LINE 文字訊息（純文字，上限 5000 字；實際約 300–500 字）"""
    r = t["regions"][reg]
    mm, dd = int(t["date"][5:7]), int(t["date"][8:10])
    tm = t["term"]
    lines = [f"【臺灣節令健康曆】{mm}/{dd}（{t['weekday']}）{reg}",
             f"節氣：{tm['name']} 第 {tm['day']} 天"]
    w = t["weather"]
    lines.append(f"天氣類型：{w['season']}・{w['type']}（NCDR {w['kind']}）" if w else "天氣類型：今日資料缺漏")
    if r["tmin"] is not None:
        lines.append(f"氣溫：{r['station']} {rr.js_fixed(r['tmin'])}–{rr.js_fixed(r['tmax'])}°C")
    hi = [x for x in r["risks"] if x["lv"] >= 2]
    for n in t["notes"]:
        lines.append(f"※ {n}")
    lines.append("")
    if not w and r["tmin"] is None:
        lines.append("今天的天氣與氣溫資料都缺漏，無法判斷風險，請到網站查看節氣提醒。")
    elif hi:
        lines.append("今天要留意（風險中以上）")
        for x in hi:
            lines.append(f"{'▲' if x['lv'] >= 3 else '△'} {x['level']}｜{x['name']}")
            lines.append(f"　高危險群：{'、'.join(x['groups'])}")
    else:
        lines.append("今天沒有風險中以上的項目。維持規律作息，依醫囑使用藥物。")
    lines +=["", f"建議做法與 14 天日曆：{t['site']}",
              "氣溫為 Open-Meteo 模式預報，非氣象署官方預報。" + (f"{t['review']}。" if t["review"] else "")]
    return "\n".join(lines)


def write_today(data: dict, now: dt.datetime | None = None) -> dict:
    t = build_today(data, now)
    SITE.mkdir(exist_ok=True)
    (SITE / "today.json").write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
    return t


# ---------------- LINE Messaging API ----------------
def line_send(token: str, mode: str, to: list[str], text: str, dedupe: str | None = None) -> str:
    """dedupe：同一個字串會產生同一個 X-Line-Retry-Key；24 小時內重送時 LINE 回 409、不會再發一次"""
    msgs = [{"type": "text", "text": text[:5000]}]
    key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"jieqi-health|{dedupe}|{mode}|{','.join(to)}")) if dedupe else str(uuid.uuid4())
    if mode == "broadcast":
        ep, body = "broadcast", {"messages": msgs}
    elif len(to) == 1:
        ep, body = "push", {"to": to[0], "messages": msgs}
    else:
        ep, body = "multicast", {"to": to[:500], "messages": msgs}
    req = urllib.request.Request(LINE_API + ep, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {token}",
        "X-Line-Retry-Key": key,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return f"{ep} HTTP {res.status}"
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return f"{ep} 今天已經送過（HTTP 409，LINE 依 retry key 判定為重複），沒有再送"
        raise RuntimeError(f"LINE {ep} 失敗 HTTP {e.code}：{e.read().decode('utf-8', 'replace')[:300]}") from None


def main() -> int:
    ap = argparse.ArgumentParser(description="產生今日摘要與 LINE 推播訊息")
    ap.add_argument("--region", choices=rr.REGIONS, help="只印出這個地區的訊息")
    ap.add_argument("--send", action="store_true", help="有 LINE_CHANNEL_ACCESS_TOKEN 時實際推播")
    ap.add_argument("--no-write", action="store_true", help="不寫 site/today.json")
    args = ap.parse_args()
    data = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    t = build_today(data) if args.no_write else write_today(data)
    if not args.no_write:
        print(f"wrote {SITE / 'today.json'}")

    if not args.send:
        for reg in ([args.region] if args.region else rr.REGIONS):
            print(f"\n===== {reg} =====\n{t['regions'][reg]['message']}")
        return 0

    region = args.region or os.environ.get("LINE_REGION") or "北部"
    if region not in rr.REGIONS:
        print(f"LINE_REGION 不正確：{region}", file=sys.stderr)
        return 2
    text = t["regions"][region]["message"]
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    mode = (os.environ.get("LINE_MODE") or "push").strip().lower()
    to = [s.strip() for s in os.environ.get("LINE_TO", "").split(",") if s.strip()]
    print(f"===== {region} =====\n{text}\n")
    if not token:
        print("沒有設定 LINE_CHANNEL_ACCESS_TOKEN，只產生訊息、不推播。")
        return 0
    if mode not in ("push", "broadcast"):
        print(f"LINE_MODE 不正確：{mode}（只能是 push 或 broadcast）", file=sys.stderr)
        return 2
    if mode == "push" and not to:
        print("push 模式需要 LINE_TO（收件者 userId），沒有設定所以不推播。")
        return 0
    print(line_send(token, mode, to, text, dedupe=f"{t['date']}|{region}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
