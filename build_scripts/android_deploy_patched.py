"""Run pyside6-android-deploy with the PYSIDE-3501 workaround.

PySide6 6.12.0's Android dependency XML lists the FFmpeg libraries with an
ABI suffix (for example ``libavcodec_arm64-v8a.so``), but the wheel ships
them without it (``libavcodec.so``).  pyside6-android-deploy passes those
suffixed names to python-for-android's ``--load-local-libs``, so the
generated ``libs.xml`` makes QtLoader eagerly load files that do not exist
in the APK.  The app then aborts before Python starts.

Keep only local libs whose suffixed name really exists in the wheel.  The
unsuffixed FFmpeg libraries are still packaged by the PySide6 recipe and are
loaded through the FFmpeg plugin's DT_NEEDED entries, so nothing is lost.

This wrapper can be removed once the host PySide6 includes the upstream fix
(6.12.1 and later).
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import PySide6

scripts_dir = Path(PySide6.__file__).parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from deploy_lib.android.android_config import AndroidConfig  # noqa: E402


def _install_workaround() -> None:
    if getattr(AndroidConfig, "_pyside3501_workaround", False):
        return

    original_find_local_libs = AndroidConfig._find_local_libs

    def find_local_libs(self):
        local_libs, plugins = original_find_local_libs(self)
        resolved = []
        for lib in local_libs:
            suffixed = self.qt_libs_path / f"lib{lib}_{self.arch}.so"
            unsuffixed = self.qt_libs_path / f"lib{lib}.so"
            if not suffixed.exists() and unsuffixed.exists():
                # p4a turns every --load-local-libs entry into
                # lib<name>_<arch>.so, which is not the name in the wheel.
                # Skipping it keeps it out of libs.xml; the linker will
                # still resolve it when the FFmpeg plugin is loaded.
                continue
            resolved.append(lib)
        return resolved, plugins

    AndroidConfig._find_local_libs = find_local_libs
    AndroidConfig._pyside3501_workaround = True


_install_workaround()

runpy.run_path(str(scripts_dir / "android_deploy.py"), run_name="__main__")
