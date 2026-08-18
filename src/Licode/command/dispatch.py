"""斜杠命令输入解析。"""


def parse(input_text: str) -> tuple[str, bool]:
    """解析零参数的 ``/<name>`` 输入。"""

    value = input_text.strip()
    if not value.startswith("/"):
        return "", False
    body = value[1:]
    if not body:
        return "", True
    if body[0].isspace():
        return "", True
    parts = body.split(maxsplit=1)
    if len(parts) != 1:
        return "", True
    return parts[0].lower(), True
