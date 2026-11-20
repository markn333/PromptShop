"""PromptShop.exe に同梱するソフトのライセンス全文を集めて、1 つのテキストにまとめる。

使い方: python tools/collect_licenses.py
出力: app/static/third_party_licenses.txt（ヘルプ画面の「ライセンス全文」で表示する）

依存するソフトを足したり入れ替えたりしたら、app/about.py の THIRD_PARTY を直してから実行し直す。
build_exe.bat は、exe を作る前にこれを実行する。
"""
import sys
from importlib import metadata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import about  # noqa: E402

OUTPUT = PROJECT_ROOT / "app" / "static" / "third_party_licenses.txt"
# ライセンスや著作権表示が入っているファイルの名前（先頭がこれで始まるもの）
_NOTICE_PREFIXES = ("license", "licence", "copying", "notice", "authors")
_RULE = "=" * 78


def _notice_files(distribution: metadata.Distribution) -> list[tuple[str, str]]:
    """配布物に入っているライセンス関係のファイルを (名前, 中身) で返す。"""
    found = []
    for entry in distribution.files or []:
        if "dist-info" not in str(entry) or not entry.name.lower().startswith(_NOTICE_PREFIXES):
            continue
        try:
            text = Path(entry.locate()).read_text(encoding="utf-8", errors="replace")
            found.append((entry.name, text.strip()))
        except OSError:
            continue
    return found


def _section(title: str, declared: str, body: str) -> str:
    return f"{_RULE}\n{title}\nライセンス: {declared}\n{_RULE}\n\n{body}\n\n"


def _python_section() -> str:
    license_file = Path(sys.base_prefix) / "LICENSE.txt"
    body = license_file.read_text(encoding="utf-8", errors="replace").strip() if license_file.exists() else ""
    version = ".".join(str(part) for part in sys.version_info[:3])
    return _section(f"Python {version}", about.PYTHON_LICENSE, body or "（ライセンスの本文を取得できませんでした）")


def build() -> tuple[str, list[str]]:
    """まとめたテキストと、本文を見つけられなかったソフトの名前を返す。"""
    parts = [
        "PromptShop.exe に同梱しているソフトウェアのライセンス\n"
        "（このファイルは tools/collect_licenses.py が作る。手で書き換えない）\n\n",
        _python_section(),
    ]
    missing = []
    for item in about.THIRD_PARTY:
        try:
            distribution = metadata.distribution(item["package"])
        except metadata.PackageNotFoundError:
            missing.append(item["name"])
            continue
        files = _notice_files(distribution)
        # メタデータにライセンスの全文を書いている配布物もある（ファイルがない場合の代わりに使う）
        inline = (distribution.metadata.get("License") or "").strip()
        if files:
            body = "\n\n".join(f"--- {name} ---\n{text}" for name, text in files)
        elif len(inline.splitlines()) > 3:
            body = inline
        else:
            body = f"（配布物にライセンスの本文が入っていません。{item['url']} を参照してください）"
            missing.append(item["name"])
        parts.append(_section(f"{item['name']} {distribution.version}", item["license"], body))
    return "".join(parts), missing


def main() -> int:
    text, missing = build()
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT} ({len(text):,} chars, {len(about.THIRD_PARTY) + 1} components)")
    if missing:
        print("license text not found for: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
