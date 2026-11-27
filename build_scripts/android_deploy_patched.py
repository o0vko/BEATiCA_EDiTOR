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

The wrapper also appends the pure Python requirements listed in
``BEATiCA_ANDROID_REQUIREMENTS`` to buildozer's ``app.requirements``, because
pyside6-android-deploy hardcodes ``python3,shiboken6,PySide6`` and would
otherwise ship an APK without the app's own dependencies.  For the same reason
``BEATiCA_ANDROID_INCLUDE_EXTS`` extends ``app.source.include_exts``, which
defaults to ``py,png,jpg,kv,atlas`` and silently drops files such as
``assets/sounds/*.wav``.  ``BEATiCA_ANDROID_ORIENTATION`` overrides
``app.orientation``, which buildozer defaults to ``portrait``.
``BEATiCA_ANDROID_PACKAGE_ID`` overrides the generated package id.

This wrapper can be removed once the host PySide6 includes the upstream fix
(6.12.1 and later).
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

import PySide6

scripts_dir = Path(PySide6.__file__).parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from deploy_lib.android.android_config import AndroidConfig  # ty: ignore[import-not-found]
from deploy_lib.android.buildozer import BuildozerConfig  # ty: ignore[import-not-found]


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


def _install_requirements_workaround() -> None:
    if getattr(BuildozerConfig, "_extra_requirements_workaround", False):
        return

    original_init = BuildozerConfig.__init__

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        extra = [
            requirement.strip()
            for requirement in os.environ.get("BEATiCA_ANDROID_REQUIREMENTS", "").split(
                ","
            )
            if requirement.strip()
        ]
        if not extra:
            return
        current = self.get_value("app", "requirements", ignore_fail=True) or ""
        merged = list(
            dict.fromkeys(
                [item.strip() for item in current.split(",") if item.strip()] + extra
            )
        )
        self.set_value("app", "requirements", ",".join(merged))
        # BuildozerConfig writes the spec file at the end of __init__; rewrite it
        # so the extra requirements reach buildozer.
        self.update_config()

    BuildozerConfig.__init__ = __init__
    BuildozerConfig._extra_requirements_workaround = True


def _install_include_exts_workaround() -> None:
    if getattr(BuildozerConfig, "_extra_include_exts_workaround", False):
        return

    original_init = BuildozerConfig.__init__

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        extra = [
            extension.strip().lstrip(".")
            for extension in os.environ.get("BEATiCA_ANDROID_INCLUDE_EXTS", "").split(
                ","
            )
            if extension.strip()
        ]
        if not extra:
            return
        current = self.get_value("app", "source.include_exts", ignore_fail=True) or ""
        merged = list(
            dict.fromkeys(
                [item.strip() for item in current.split(",") if item.strip()] + extra
            )
        )
        self.set_value("app", "source.include_exts", ",".join(merged))
        # BuildozerConfig writes the spec file at the end of __init__; rewrite it
        # so the extra extensions reach buildozer.
        self.update_config()

    BuildozerConfig.__init__ = __init__
    BuildozerConfig._extra_include_exts_workaround = True


def _install_orientation_workaround() -> None:
    if getattr(BuildozerConfig, "_orientation_workaround", False):
        return

    original_init = BuildozerConfig.__init__

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        orientation = os.environ.get("BEATiCA_ANDROID_ORIENTATION", "").strip()
        if not orientation:
            return
        # buildozer defaults to portrait, which is wrong for a chart editor.
        self.set_value("app", "orientation", orientation)
        # BuildozerConfig writes the spec file at the end of __init__; rewrite it
        # so the orientation reaches buildozer.
        self.update_config()

    BuildozerConfig.__init__ = __init__
    BuildozerConfig._orientation_workaround = True


def _install_package_workaround() -> None:
    if getattr(BuildozerConfig, "_package_id_workaround", False):
        return

    original_init = BuildozerConfig.__init__

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        package_id = os.environ.get("BEATiCA_ANDROID_PACKAGE_ID", "").strip()
        if not package_id:
            return
        # buildozer は domain と name を繋いで package を作る
        domain, _, name = package_id.rpartition(".")
        if not domain:
            return
        self.set_value("app", "package.domain", domain)
        self.set_value("app", "package.name", name)
        # BuildozerConfig writes the spec file at the end of __init__; rewrite it
        # so the package id reaches buildozer.
        self.update_config()

    BuildozerConfig.__init__ = __init__
    BuildozerConfig._package_id_workaround = True


_install_workaround()
_install_requirements_workaround()
_install_include_exts_workaround()
_install_orientation_workaround()
_install_package_workaround()

runpy.run_path(str(scripts_dir / "android_deploy.py"), run_name="__main__")
