"""ツールバー用アイコン PNG を Font Awesome から生成する（開発用）。

アプリ本体は qtawesome に依存しない。ここで生成した PNG を
assets/images/icons/toolbar/ に置き、全プラットフォームで同じ画像を使う。
再生成が必要なときだけ `uv run python build_scripts/generate_toolbar_icons.py`
を実行する（要 qtawesome / PySide6）。
"""

import sys
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets" / "images" / "icons" / "toolbar"

ICONS = {
    "select": "fa5s.mouse-pointer",
    "zoom_in": "fa5s.search-plus",
    "zoom_out": "fa5s.search-minus",
    "snap_ignore": "fa5s.magnet",
    "copy": "fa5s.copy",
    "paste": "fa5s.paste",
    "delete": "fa5s.trash",
    "step_back": "fa5s.step-backward",
    "stop": "fa5s.stop",
    "play_pause": "fa5s.play",
    "pause": "fa5s.pause",
    "step_forward": "fa5s.step-forward",
}


def main() -> None:
    # アイコンの描画には QGuiApplication が必要（ウィンドウは作らない）
    app = QGuiApplication(sys.argv[:1])
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for filename, icon_name in ICONS.items():
        pixmap = qta.icon(icon_name, color="#ffffff").pixmap(QSize(256, 256))
        if pixmap.isNull():
            raise RuntimeError(f"failed to render {icon_name}")
        path = OUT_DIR / f"{filename}.png"
        if not pixmap.save(str(path), "PNG"):
            raise RuntimeError(f"failed to save {path}")
        print(f"wrote {path.relative_to(ROOT)}")

    # app は描画中だけ保持すればよい
    del app


if __name__ == "__main__":
    main()
