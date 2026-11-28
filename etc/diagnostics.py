"""未捕捉例外をファイルに残すための診断用フック。

iOS では Python の未捕捉例外でプロセスが終了してもクラッシュレポートが
残らない。Documents/beatica.log に traceback を書き出すことで、実機で
何が起きたかを後から確認できるようにする（iOS 以外では何もしない）。
"""

import faulthandler
import sys
import traceback
from datetime import datetime
from pathlib import Path

_fault_file = None


def _logPath() -> Path | None:
    if sys.platform != "ios":
        return None
    try:
        documents = Path.home() / "Documents"
        documents.mkdir(parents=True, exist_ok=True)
        return documents / "beatica.log"
    except OSError:
        return None


_LOG_PATH = _logPath()


def _append(text: str) -> None:
    if _LOG_PATH is None:
        return
    try:
        # 無限に膨らまないよう、512KB を超えたら作り直す
        if _LOG_PATH.exists() and _LOG_PATH.stat().st_size > 512 * 1024:
            _LOG_PATH.unlink()
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def log(text: str) -> None:
    """任意のメッセージをログへ残す（iOS 以外では何もしない）"""
    _append(text)


def install() -> None:
    """iOS のときだけ excepthook / faulthandler をファイル出力に差し替える。"""
    global _fault_file
    if _LOG_PATH is None:
        return

    _append(
        f"\n=== BEATiCA EDiTOR start "
        f"{datetime.now().isoformat(timespec='seconds')} ===\n"
    )

    try:
        _fault_file = _LOG_PATH.open("a", encoding="utf-8")
        faulthandler.enable(_fault_file, all_threads=True)
    except OSError:
        _fault_file = None

    previous = sys.excepthook

    def hook(exc_type, exc_value, exc_tb):
        _append(
            "\n[uncaught] "
            + datetime.now().isoformat(timespec="seconds")
            + "\n"
            + "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        )
        previous(exc_type, exc_value, exc_tb)

    sys.excepthook = hook
