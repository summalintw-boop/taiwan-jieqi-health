"""舊名稱保留：改用 build_pages.py（同時產生 v2 與 v3）。"""
from build_pages import build

if __name__ == "__main__":
    build("page_v2.html", "v2")
    build("page_v3.html", "v3")
    build("page_v4.html", "v4")
