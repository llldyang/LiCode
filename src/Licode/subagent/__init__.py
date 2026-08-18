"""SubAgent 角色定义、解析与目录加载。"""

from .catalog import Catalog, load_catalog
from .definition import BUILTIN, PLUGIN, PROJECT, USER, Definition, Source
from .embed import builtin_definitions
from .parser import parse_definition, parse_file

__all__ = [
    "BUILTIN",
    "PLUGIN",
    "PROJECT",
    "USER",
    "Catalog",
    "Definition",
    "Source",
    "builtin_definitions",
    "load_catalog",
    "parse_definition",
    "parse_file",
]
