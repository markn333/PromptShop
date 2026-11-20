"""アプリの名前・バージョン・ライセンスと、同梱しているソフトの一覧（ヘルプ画面に出す）。"""

APP_NAME = "PromptShop"
# バージョンは「大きな変更.機能の追加.修正」。機能を足したら真ん中を、直しただけなら右端を上げる。
APP_VERSION = "1.1.0"
COPYRIGHT = "Copyright (c) 2026 REDSUN"
LICENSE_NAME = "MIT License"

PYTHON_LICENSE = "PSF-2.0"

# PromptShop.exe に同梱しているソフト（Python 本体は別に扱う）。
# license は、各配布物のメタデータで 2026-11-20 に確認したもの。
# 依存するソフトを足したり入れ替えたりしたら、ここを直して tools/collect_licenses.py を実行し直す。
THIRD_PARTY = (
    {"name": "FastAPI", "package": "fastapi", "license": "MIT", "url": "https://github.com/fastapi/fastapi"},
    {"name": "Starlette", "package": "starlette", "license": "BSD-3-Clause", "url": "https://github.com/encode/starlette"},
    {"name": "Uvicorn", "package": "uvicorn", "license": "BSD-3-Clause", "url": "https://github.com/encode/uvicorn"},
    {"name": "Pydantic", "package": "pydantic", "license": "MIT", "url": "https://github.com/pydantic/pydantic"},
    {"name": "pydantic-core", "package": "pydantic-core", "license": "MIT", "url": "https://github.com/pydantic/pydantic-core"},
    {"name": "HTTPX", "package": "httpx", "license": "BSD-3-Clause", "url": "https://github.com/encode/httpx"},
    {"name": "HTTPCore", "package": "httpcore", "license": "BSD-3-Clause", "url": "https://github.com/encode/httpcore"},
    {"name": "Pillow", "package": "pillow", "license": "HPND", "url": "https://github.com/python-pillow/Pillow"},
    {"name": "python-dotenv", "package": "python-dotenv", "license": "BSD-3-Clause", "url": "https://github.com/theskumar/python-dotenv"},
    {"name": "python-multipart", "package": "python-multipart", "license": "Apache-2.0", "url": "https://github.com/Kludex/python-multipart"},
    {"name": "pywebview", "package": "pywebview", "license": "BSD-3-Clause", "url": "https://github.com/r0x0r/pywebview"},
    {"name": "Python.NET", "package": "pythonnet", "license": "MIT", "url": "https://github.com/pythonnet/pythonnet"},
    {"name": "clr-loader", "package": "clr-loader", "license": "MIT", "url": "https://github.com/pythonnet/clr-loader"},
    {"name": "Bottle", "package": "bottle", "license": "MIT", "url": "https://github.com/bottlepy/bottle"},
    {"name": "proxy_tools", "package": "proxy-tools", "license": "MIT", "url": "https://github.com/jtushman/proxy_tools"},
    {"name": "AnyIO", "package": "anyio", "license": "MIT", "url": "https://github.com/agronholm/anyio"},
    {"name": "h11", "package": "h11", "license": "MIT", "url": "https://github.com/python-hyper/h11"},
    {"name": "idna", "package": "idna", "license": "BSD-3-Clause", "url": "https://github.com/kjd/idna"},
    {"name": "sniffio", "package": "sniffio", "license": "MIT OR Apache-2.0", "url": "https://github.com/python-trio/sniffio"},
    {"name": "certifi", "package": "certifi", "license": "MPL-2.0", "url": "https://github.com/certifi/python-certifi"},
    {"name": "typing-extensions", "package": "typing-extensions", "license": "PSF-2.0", "url": "https://github.com/python/typing_extensions"},
    {"name": "annotated-types", "package": "annotated-types", "license": "MIT", "url": "https://github.com/annotated-types/annotated-types"},
    {"name": "typing-inspection", "package": "typing-inspection", "license": "MIT", "url": "https://github.com/pydantic/typing-inspection"},
    {"name": "click", "package": "click", "license": "BSD-3-Clause", "url": "https://github.com/pallets/click"},
    {"name": "colorama", "package": "colorama", "license": "BSD-3-Clause", "url": "https://github.com/tartley/colorama"},
    {"name": "cffi", "package": "cffi", "license": "MIT", "url": "https://github.com/python-cffi/cffi"},
    {"name": "pycparser", "package": "pycparser", "license": "BSD-3-Clause", "url": "https://github.com/eliben/pycparser"},
    {"name": "exceptiongroup", "package": "exceptiongroup", "license": "MIT", "url": "https://github.com/agronholm/exceptiongroup"},
    {
        "name": "PyInstaller（起動部分）", "package": "pyinstaller",
        "license": "GPL-2.0-or-later（同梱したアプリを別のライセンスで配布できる例外つき）",
        "url": "https://github.com/pyinstaller/pyinstaller",
    },
)
