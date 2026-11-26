[app]
title = BEAEDiT
project_dir = .
input_file = main.py
exec_directory = dist
project_file = 
icon = C:\Users\nennneko5787\Documents\organizations\musica-lab\BEATiCA_EDiTOR\res\icon.ico

[python]
packages = Nuitka==4.1.1
android_packages = buildozer==1.6.0,cython==0.29.33

[qt]
modules = Core,Gui,Multimedia,Widgets
plugins = imageformats,multimedia,platforms,platforminputcontexts,platformthemes,styles,wayland-decoration-client,wayland-graphics-integration-client,wayland-shell-integration,xcbglintegrations
qml_files = 

[android]
wheel_pyside = 
wheel_shiboken = 
plugins = imageformats_qjpeg,multimedia_androidmediaplugin,multimedia_ffmpegmediaplugin,platforms_qtforandroid,styles_qandroidstyle

[ios]
wheel_pyside = 
wheel_shiboken = 
xcframework_path = 
bundle_id = 
team_id = 
version = 1.0
deployment_target = 
entitlements = 
signing_style = Automatic
header_search_paths = 

[nuitka]
macos.permissions = 
mode = standalone
extra_args = --quiet --noinclude-qt-translations --include-data-dir=assets=assets --assume-yes-for-downloads

[buildozer]
mode = debug
log_level = 2
recipe_dir = 
jars_dir = 
ndk_path = 
sdk_path = 
local_libs = 
arch = 

