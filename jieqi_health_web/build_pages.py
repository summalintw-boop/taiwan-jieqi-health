"""產生今日健康提醒（site/v2/）與健康節令曆（site/v3/）；site/v4/ 只是轉址到 v3（原「節令曆＋疾管署歷史」已併入）

- 風險規則：從 page.html 擷取「天文」到「繪製：今日摘要」之間的程式，三個版本規則一致。
- 共用元件：parts/shared_ui.js（官方出處的就醫警訊、原因說明）、parts/bp.*（血壓追蹤）。
page.html 或 parts/ 改了以後，重新執行：python build_pages.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARTS = HERE / "parts"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def sync_main_sources() -> None:
    """把 parts/sources.html 同步進 page.html（完整版由 update_data.py 產生，不經過 build）。"""
    p = HERE / "page.html"
    s = read(p)
    a, b = "<!--SOURCES_BEGIN-->", "<!--SOURCES_END-->"
    i, j = s.index(a) + len(a), s.index(b)
    new = s[:i] + "\n" + read(PARTS / "sources.html") + s[j:]
    if new != s:
        p.write_text(new, encoding="utf-8")
        print("synced sources into page.html")


def redirect(out_dir: str, to: str) -> None:
    """舊網址轉到新網址（GitHub Pages 不能設伺服器轉址，用 meta refresh）"""
    doc = ("<!doctype html>\n<html lang=\"zh-Hant-TW\">\n<head>\n<meta charset=\"utf-8\">\n"
           f"<meta http-equiv=\"refresh\" content=\"0; url={to}\">\n<link rel=\"canonical\" href=\"{to}\">\n"
           "<title>健康節令曆</title>\n</head>\n<body>\n"
           f"<p>「節令曆＋疾管署歷史」已併入<a href=\"{to}\">健康節令曆</a>，正在轉到新網址…</p>\n</body>\n</html>\n")
    out = HERE / "site" / out_dir / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print("wrote", out.relative_to(HERE), "(redirect)")


def build(template: str, out_dir: str) -> None:
    main = read(HERE / "page.html")
    rules = main[main.index("// ===== 天文：太陽視黃經 ====="):main.index("// ===== 繪製：今日摘要 =====")]
    body = read(HERE / template)
    for key, val in (("/*@@RULES@@*/", rules), ("/*@@SHARED@@*/", read(PARTS / "shared_ui.js")),
                     ("<!--@@BP_HTML@@-->", read(PARTS / "bp.html")), ("/*@@BP_CSS@@*/", read(PARTS / "bp.css")),
                     ("/*@@BP_JS@@*/", read(PARTS / "bp.js")), ("<!--@@SOURCES@@-->", read(PARTS / "sources.html"))):
        assert key in body, f"{template} 缺少 {key}"
        body = body.replace(key, val)
    doc = ("<!doctype html>\n<html lang=\"zh-Hant-TW\">\n<head>\n<meta charset=\"utf-8\">\n"
           "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'none'\">\n"  # 內容安全政策（資安加固）：只允許本站與 Google Fonts 的資源
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
           "<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}"
           "img{max-width:100%}[hidden]{display:none!important}</style>\n</head>\n<body>\n" + body + "\n</body>\n</html>\n")
    out = HERE / "site" / out_dir / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print("wrote", out.relative_to(HERE), len(doc), "bytes")


if __name__ == "__main__":
    sync_main_sources()
    build("page_v2.html", "v2")
    build("page_v3.html", "v3")
    redirect("v4", "../v3/")
