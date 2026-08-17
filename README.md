# LiCode

LiCode 是一个使用 Python 实现的终端 AI 编程助手。

当前版本提供 Anthropic 与 OpenAI 两种协议的纯文本流式多轮对话，以及基于 Textual 的终端界面。

## 启动

```powershell
uv sync
Copy-Item .Licode/config.yaml.example .Licode/config.yaml
uv run Licode
```

请在本地配置文件中填写真实的 API 密钥。`.Licode/config.yaml` 已被 Git 忽略。
