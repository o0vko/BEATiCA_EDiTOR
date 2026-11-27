"""assets/ を Qt リソース (assets.qrc -> assets_rc.py) に変換する。

pyside6-ios-deploy はプロジェクト内の .py ファイルしかバンドルへコピーせず、
assets/ のようなデータファイルは含めない。iOS ビルドの直前にこのスクリプトを
実行し、生成された assets_rc.py をアプリへ同梱する。
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "assets"
QRC_PATH = ROOT / "assets.qrc"
RC_PATH = ROOT / "assets_rc.py"


def write_qrc() -> None:
    files = sorted(path for path in ASSETS_DIR.rglob("*") if path.is_file())
    # <file> は .qrc からの相対パスなので assets/ を付ける。
    # prefix="/" と組み合わせて実行時のパスを ":/assets/..." にする。
    lines = [
        "<!DOCTYPE RCC>",
        '<RCC version="1.0">',
        '    <qresource prefix="/">',
    ]
    for path in files:
        lines.append(
            f"        <file>assets/{path.relative_to(ASSETS_DIR).as_posix()}</file>"
        )
    lines += ["    </qresource>", "</RCC>", ""]
    QRC_PATH.write_text("\n".join(lines), encoding="utf-8")


def find_rcc() -> str:
    executable = Path(sys.executable).with_name("pyside6-rcc")
    if sys.platform == "win32":
        executable = executable.with_suffix(".exe")
    if executable.is_file():
        return str(executable)

    found = shutil.which("pyside6-rcc")
    if found:
        return found

    raise FileNotFoundError("pyside6-rcc が見つかりません（PySide6 を入れてください）")


def main() -> None:
    write_qrc()
    subprocess.run([find_rcc(), str(QRC_PATH), "-o", str(RC_PATH)], check=True)
    print(f"wrote {RC_PATH.relative_to(ROOT)} ({RC_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
