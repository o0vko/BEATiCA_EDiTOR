from PIL import Image

image = Image.open("res/icon.png").convert("RGBA")

# Windows ICO
image.save(
    "res/icon.ico",
    format="ICO",
    sizes=[
        (16, 16),
        (24, 24),
        (32, 32),
        (48, 48),
        (64, 64),
        (128, 128),
        (256, 256),
    ],
)

# macOS ICNS
image.save(
    "res/icon.icns",
    format="ICNS",
)

print("Successfully converted!")
