from pathlib import Path

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
ASSETS_PATH = Path("assets/")
IMAGES_PATH = ASSETS_PATH / "images"

# notes view
NOTE_WIDTH = 20
NOTE_HEIGHT = 5  # 本来は width / 4
LANE_COUNT = 16
PIXELS_PER_SECOND = 100
PLAYHEAD_VIEWPORT_RATIO = (
    0.8  # 再生中、シークバーをビューポートのどの高さに固定するか（0.0=上端, 1.0=下端）
)
WAVEFORM_BUCKET_SECONDS = (
    0.01  # 波形の解像度（PIXELS_PER_SECOND=100 なので 10ms = 1px）
)
