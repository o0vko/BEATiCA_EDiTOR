from pathlib import Path

WINDOW_WIDTH = 1920
WINDOW_HEIGHT = 1080
ASSETS_PATH = Path("assets/")
IMAGES_PATH = ASSETS_PATH / "images"
SOUNDS_PATH = ASSETS_PATH / "sounds"

# notes view
NOTE_WIDTH = 20
NOTE_HEIGHT = 5  # 本来は width / 4
LANE_COUNT = 16
PIXELS_PER_SECOND = 500
PLAYHEAD_VIEWPORT_RATIO = (
    0.8  # 再生中、シークバーをビューポートのどの高さに固定するか（0.0=上端, 1.0=下端）
)
WAVEFORM_BUCKET_SECONDS = (
    0.001  # 波形の解像度（PIXELS_PER_SECOND=100 なので 10ms = 1px）
)
DEBUG_HITBOX = False  # デバッグ: 当たり判定を薄く表示

# 内部クロックと音源のズレがこの秒数を超えたときだけ音源に再同期する
AUDIO_RESYNC_THRESHOLD = 0.15

# 音源が無い場合でも確保する最小の譜面長（小節数）
MIN_MEASURES = 16

# ズーム（縦方向の表示倍率）の下限・上限
ZOOM_MIN = 0.1
ZOOM_MAX = 20.0
ZOOM_STEP = 1.1

# スナップの候補（1拍あたりの分割数）。大きいほど細かい
SNAP_OPTIONS = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 480, 1920]

# レーン区切り（表示グリッド分割数）の候補
LANE_DIVISIONS = [2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 96, 192]

# ズーム倍率の候補（コンボボックス用）
ZOOM_PRESETS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0]

# FrontViewのスカイノーツY座標（5.0でちょうど1、表示範囲は下=-1.0〜上=5.0）
POSITION_Y_MAX = 5.0
POSITION_Y_VIEW_MIN = -2.0
POSITION_Y_VIEW_MAX = 7.0
