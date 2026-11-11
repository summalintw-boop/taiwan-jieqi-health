"""產生第二版（今日健康提醒，site/v2/）與第三版（節令健康曆，site/v3/）

- 風險規則：從 page.html 擷取「天文」到「繪製：今日摘要」之間的程式，三個版本規則一致。
- 共用元件：parts/shared_ui.js（官方出處的就醫警訊、原因說明）、parts/bp.*（血壓追蹤）。
page.html 或 parts/ 改了以後，重新執行：python build_pages.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARTS = HERE / "parts"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def build(template: str, out_dir: str) -> None:
    main = read(HERE / "page.html")
    rules = main[main.index("// ===== 天文：太陽視黃經 ====="):main.index("// ===== 繪製：今日摘要 =====")]
    body = read(HERE / template)
    for key, val in (("/*@@RULES@@*/", rules), ("/*@@SHARED@@*/", read(PARTS / "shared_ui.js")),
                     ("<!--@@BP_HTML@@-->", read(PARTS / "bp.html")), ("/*@@BP_CSS@@*/", read(PARTS / "bp.css")),
                     ("/*@@BP_JS@@*/", read(PARTS / "bp.js"))):
        assert key in body, f"{template} 缺少 {key}"
        body = body.replace(key, val)
    doc = ("<!doctype html>\n<html lang=\"zh-Hant-TW\">\n<head>\n<meta charset=\"utf-8\">\n"
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
           "<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}"
           "img{max-width:100%}[hidden]{display:none!important}</style>\n</head>\n<body>\n" + body + "\n</body>\n</html>\n")
    out = HERE / "site" / out_dir / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print("wrote", out.relative_to(HERE), len(doc), "bytes")


if __name__ == "__main__":
    build("page_v2.html", "v2")
    build("page_v3.html", "v3")
