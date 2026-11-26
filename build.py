import configparser
import os
import platform
import re
import subprocess
from pathlib import Path

import zipfile


ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "pysidedeploy.spec"

# Pure Python packages the app imports at runtime.  pyside6-android-deploy only
# installs python3/shiboken6/PySide6, so these are appended to app.requirements
# and installed by python-for-android's pip step.
ANDROID_REQUIREMENTS = "qtawesome,qtpy"

# File extensions p4a must copy into the APK.  Its default list
# (py,png,jpg,kv,atlas) drops the app's sound effects.
ANDROID_INCLUDE_EXTS = "wav"

# buildozer defaults to portrait; the editor is designed for landscape.
ANDROID_ORIENTATION = "landscape"


def verify_android_apk(apk: Path) -> None:
    """Make sure QtLoader cannot reference a native library missing from the APK."""
    with zipfile.ZipFile(apk) as archive:
        native_libs = {
            Path(name).name
            for name in archive.namelist()
            if name.startswith("lib/") and name.endswith(".so")
        }
        abis = {
            name.split("/")[1]
            for name in archive.namelist()
            if name.startswith("lib/") and name.count("/") >= 2
        }
        resources = archive.read("resources.arsc")

    referenced = {
        match.decode("ascii")
        for match in re.findall(rb"lib[A-Za-z0-9_.+-]+\.so", resources)
    }
    missing = sorted(
        lib
        for lib in referenced
        if any(lib.endswith(f"_{abi}.so") for abi in abis)
        and lib not in native_libs
    )
    if missing:
        raise RuntimeError(
            f"{apk.name}: QtLoader references libraries that are not packaged: "
            + ", ".join(missing)
        )

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

        # pyside6-android-deploy を必ず使う（buildozerは使わない）。
        # 6.12.0 の FFmpeg ライブラリ名の不具合 (PYSIDE-3501) を避けるため
        # ラッパー経由で起動する。
        import sys

        cmd = [
            sys.executable,
            str(ROOT / "build_scripts" / "android_deploy_patched.py"),
            "-c",
            str(CONFIG_PATH),
        ]
        # pyside6-android-deploy hardcodes app.requirements, so the app's own
        # pure Python dependencies have to be appended by the wrapper.
        env = os.environ.copy()
        env["BEATiCA_ANDROID_REQUIREMENTS"] = ANDROID_REQUIREMENTS
        env["BEATiCA_ANDROID_INCLUDE_EXTS"] = ANDROID_INCLUDE_EXTS
        env["BEATiCA_ANDROID_ORIENTATION"] = ANDROID_ORIENTATION
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
        result = subprocess.run(cmd, check=False, cwd=ROOT, env=env)
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
        for apk in glob.glob(str(ROOT / "dist" / "*.apk")):
            verify_android_apk(Path(apk))
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