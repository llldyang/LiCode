"""读取随 wheel 发布的内置 SubAgent 定义。"""

from importlib.resources import files

from .definition import Definition, Source
from .parser import parse_definition


def builtin_definitions() -> list[Definition]:
    """返回按名称排序的全部内置角色，解析失败直接抛出。"""

    package = files("Licode.subagent.builtin")
    definitions = [
        parse_definition(item.read_bytes(), f"builtin:{item.name}", Source.BUILTIN)
        for item in package.iterdir()
        if item.name.endswith(".md")
    ]
    return sorted(definitions, key=lambda item: item.name)
