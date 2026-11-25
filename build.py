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
        import glob
        import shutil

        icon_path = ROOT / "res" / "icon.png"
        if not icon_path.is_file():
            raise FileNotFoundError(icon_path)
        config.set("app", "icon", str(icon_path.resolve()))
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            config.write(f)

        arch = os.environ.get("BUILD_ARCH", "aarch64")

        android_deploy = shutil.which("pyside6-android-deploy")
        qtpip = shutil.which("qtpip")

        # 1) Android用PySide6 wheelを取得（qtpip）
        wheel_pyside = wheel_shiboken = None
        if qtpip is not None:
            subprocess.run(
                [qtpip, "download", "PySide6", "--android", "--arch", arch],
                cwd=ROOT,
                check=True,
            )
            pyside = sorted(glob.glob(str(ROOT / "PySide6-*.whl")))
            shiboken = sorted(glob.glob(str(ROOT / "shiboken6-*.whl")))
            wheel_pyside = pyside[-1] if pyside else None
            wheel_shiboken = shiboken[-1] if shiboken else None

        if android_deploy:
            cmd = [android_deploy, "-c", str(CONFIG_PATH)]
            if wheel_pyside:
                cmd += ["--wheel-pyside", wheel_pyside]
            if wheel_shiboken:
                cmd += ["--wheel-shiboken", wheel_shiboken]
            subprocess.run(cmd, cwd=ROOT, check=True)
            return

        # pyside6-android-deployが無い場合はbuildozerでビルド
        buildozer = shutil.which("buildozer")
        if buildozer is None:
            raise RuntimeError(
                "Androidビルドには pyside6-android-deploy か (qtpip + buildozer) が必要です。"
                "uv sync --group android で導入してください。"
            )
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