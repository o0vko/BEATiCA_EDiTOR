import configparser
import os
import platform
import subprocess
from pathlib import Path

import zipfile

for wheel in (wheel_pyside, wheel_shiboken):
    if not wheel:
        continue

    print(f"\n[ANDROID DEBUG] Inspecting {wheel}")

    with zipfile.ZipFile(wheel) as z:
        for entry in z.namelist():
            if ".so" in entry and (
                "plugin" in entry.lower()
                or "avcodec" in entry.lower()
                or "avformat" in entry.lower()
                or "avutil" in entry.lower()
            ):
                print(f"[ANDROID DEBUG] {entry}")

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
        import urllib.request

        icon_path = ROOT / "res" / "icon.png"
        if not icon_path.is_file():
            raise FileNotFoundError(icon_path)
        config.set("app", "icon", str(icon_path.resolve()))
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            config.write(f)

        arch = os.environ.get("BUILD_ARCH", "aarch64")
        import PySide6

        version = PySide6.__version__
        base = "https://download.qt.io/official_releases/QtForPython"

        def download(url: str, dest: Path) -> bool:
            try:
                print(f"[ANDROID] Downloading {url}")
                urllib.request.urlretrieve(url, dest)
                return True
            except Exception as e:  # noqa: BLE001
                print(f"[ANDROID] Failed to download {url}: {e}")
                return False

        # PySide6 / shiboken6 のAndroid wheelを取得（cpタグは候補を順に試す）
        wheel_pyside = wheel_shiboken = None
        for tag in ("cp310-abi3", "cp311-cp311", "cp39-abi3"):
            pyside_name = f"pyside6-{version}-{version}-{tag}-android_{arch}.whl"
            shiboken_name = (
                f"shiboken6-{version}-{version}-{tag}-android_{arch}.whl"
            )
            pyside_ok = download(f"{base}/pyside6/{pyside_name}", ROOT / pyside_name)
            shiboken_ok = download(
                f"{base}/shiboken6/{shiboken_name}", ROOT / shiboken_name
            )
            if pyside_ok and shiboken_ok:
                wheel_pyside = str(ROOT / pyside_name)
                wheel_shiboken = str(ROOT / shiboken_name)
                break

        # pyside6-android-deploy を必ず使う（buildozerは使わない）
        import shutil
        import sys

        android_deploy = shutil.which("pyside6-android-deploy")
        if android_deploy:
            cmd = [android_deploy, "-c", str(CONFIG_PATH)]
        else:
            cmd = [
                sys.executable,
                "-m",
                "PySide6.scripts.android_deploy",
                "-c",
                str(CONFIG_PATH),
            ]
        if wheel_pyside:
            cmd += ["--wheel-pyside", wheel_pyside]
        if wheel_shiboken:
            cmd += ["--wheel-shiboken", wheel_shiboken]
        # SDK/NDKが環境変数にあれば明示的に渡す（build-tools入りSDK）
        sdk_path = os.environ.get("ANDROID_SDK_ROOT")
        ndk_path = os.environ.get("ANDROID_NDK_HOME")
        if sdk_path:
            cmd += ["--sdk-path", sdk_path]
        if ndk_path:
            cmd += ["--ndk-path", ndk_path]
        # NDK API レベルは buildozer.spec / 環境変数 (ANDROIDMINAPI) 側で制御
        result = subprocess.run(cmd, check=False, cwd=ROOT)
        # 終了コード、または成果物(apk/aab)が無ければ失敗扱い
        import glob

        produced = glob.glob(str(ROOT / "dist" / "*.apk")) + glob.glob(
            str(ROOT / "dist" / "*.aab")
        )
        if result.returncode != 0 or not produced:
            print(
                f"[ANDROID] failed (code {result.returncode}, "
                f"apk/aab={len(produced)})"
            )
            sys.exit(1)
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

    result = subprocess.run(
        ["pyside6-deploy", "-c", str(CONFIG_PATH)],
        check=False,
        cwd=ROOT,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()