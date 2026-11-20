from ursina import *
from ursina.prefabs.hot_reloader import HotReloader

app = Ursina(title="BEATiCA EDiTOR")
hotReloader = HotReloader()


def main():
    text_entity = Text("hello")

    app.run()


if __name__ == "__main__":
    main()
