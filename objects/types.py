import dataclasses


@dataclasses.dataclass(kw_only=True)
class FixedInteger:
    major: int
    minor: int
