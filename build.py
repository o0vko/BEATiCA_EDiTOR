import configparser
import os
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "pysidedeploy.spec"

ICONS = {
    "Windows": "res/icon.ico",
    "Darwin": "res/icon.icns",
    "Linux": "res/icon.png",
}


def main():
    target = os.environ.get("BUILD_TARGET", "").strip().lower()

    config = configparser.ConfigParser()
    if not config.read(CONFIG_PATH, encoding="utf-8"):
        raise FileNotFoundError(CONFIG_PATH)

    if target == "android":
        # Androidはpyside6-deploy（デスクトップ専用）では作れない。
        # pyside6-android-deploy があればそれを使い、無ければ buildozer を使う。
        import shutil

        icon_path = ROOT / "res" / "icon.png"
        if not icon_path.is_file():
            raise FileNotFoundError(icon_path)
        config.set("app", "icon", str(icon_path.resolve()))
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            config.write(f)

        android_deploy = shutil.which("pyside6-android-deploy")
        if android_deploy:
            # 1) Android用PySide6 wheelを取得
            subprocess.run(
                [android_deploy, "-c", str(CONFIG_PATH)], cwd=ROOT, check=True
            )
            return

        # qtpipでAndroid wheelを取得してからbuildozerでビルド
        qtpip = shutil.which("qtpip")
        if qtpip is None:
            raise RuntimeError(
                "Androidビルドには pyside6-android-deploy か (qtpip + buildozer) が必要です。"
                "uv sync --group android で導入してください。"
            )
        arch = os.environ.get("BUILD_ARCH", "aarch64")
        subprocess.run(
            [qtpip, "download", "PySide6", "--android", "--arch", arch],
            cwd=ROOT,
            check=True,
        )
        buildozer = shutil.which("buildozer")
        if buildozer is None:
            raise RuntimeError("buildozer が見つかりません。uv sync --group android を実行してください。")
        subprocess.run([buildozer, "android", "debug"], cwd=ROOT, check=True)
        return

    system = platform.system()
    icon = ICONS.get(system)
    if icon is None:
        raise RuntimeError(f"Unsupported platform: {system}")

    icon_path = ROOT / icon
    if not icon_path.is_file():
        raise FileNotFoundError(icon_path)

    config.set("app", "icon", str(icon_path.resolve()))

    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        config.write(f)

    subprocess.run(
        ["pyside6-deploy", "-c", str(CONFIG_PATH)],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()