"""產生簡易版（今日健康提醒）網頁：site/v2/index.html

風險規則不另外複製，而是每次從 page.html 擷取「天文」到「繪製：今日摘要」之間的程式，
確保兩個版型的規則一致。page.html 改了規則後重新執行本程式即可。
用法：python build_v2.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
main = (HERE / "page.html").read_text(encoding="utf-8")
start = main.index("// ===== 天文：太陽視黃經 =====")
end = main.index("// ===== 繪製：今日摘要 =====")
rules = main[start:end]

tpl = (HERE / "page_v2.html").read_text(encoding="utf-8")
assert "/*@@RULES@@*/" in tpl
body = tpl.replace("/*@@RULES@@*/", rules)
doc = ("<!doctype html>\n<html lang=\"zh-Hant-TW\">\n<head>\n<meta charset=\"utf-8\">\n"
       "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
       "<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}"
       "img{max-width:100%}[hidden]{display:none!important}</style>\n</head>\n<body>\n" + body + "\n</body>\n</html>\n")
out = HERE / "site" / "v2" / "index.html"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(doc, encoding="utf-8")
print("wrote", out, len(doc), "bytes")
