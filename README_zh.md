# cli-agent-mcp

[English](README.md)

统一的 MCP（Model Context Protocol）服务器，用于 CLI AI 代理。提供单一接口调用 Codex、Gemini、Claude 和 OpenCode CLI 工具。

## 为什么选择 cli-agent-mcp？

这不只是 CLI 的封装 —— 这是一种**多模型协作的调度模式**。

**说不清楚需求？** 让 Claude 来调度。描述你想要什么，它会把模糊的想法分解成具体的任务，分配给合适的 agent。委派的过程本身就在迫使你理清思路。

**规划宏大的产品愿景？** 每个模型带来独特的视角：
- **Codex**：批评家。锐利的分析目光捕捉你遗漏的细节，挑战假设，发现边界情况。
- **Gemini**：创意者。发散思维，意想不到的连接，那些你不知道自己需要的灵感火花。
- **Claude**：书记员。忠实执行，清晰文档，把想法变成可运行的代码。

**想要持久化结果？** 使用 `save_file` 捕获 agent 输出，然后让 Claude 综合多次分析的洞察。

我们不只是封装 CLI —— 我们提供一种**人机协作的思维框架**。

## 特性

- **统一接口**：单个 MCP 服务器暴露多个 CLI 代理
- **GUI 仪表盘**：使用 pywebview 实时监控任务
- **请求隔离**：每请求执行上下文，支持安全并发
- **信号处理**：通过 SIGINT 优雅取消，不会终止服务器
- **调试日志**：全面的子进程输出捕获，便于调试

## 截图

![CLI Agent MCP GUI](dev-docs/screenshot/screenshot.png)

## 安装

```bash
# 从 PyPI 安装（发布后）
uvx cli-agent-mcp

# 从 GitHub 安装
uvx --from git+https://github.com/shiharuharu/cli-agent-mcp.git cli-agent-mcp

# 从源码安装（开发模式）
uvx --from /path/to/cli-agent-mcp cli-agent-mcp

# 或使用 pip
pip install -e .
```

## 配置

通过环境变量配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CAM_TOOLS` | 允许的工具列表，逗号分隔（空=全部） | `""`（全部） |
| `CAM_GUI` | 启用 GUI 仪表盘 | `true` |
| `CAM_GUI_DETAIL` | GUI 详细模式 | `false` |
| `CAM_GUI_KEEP` | 退出时保留 GUI | `false` |
| `CAM_DEBUG` | MCP 响应中包含调试信息 | `false` |
| `CAM_LOG_DEBUG` | 将调试日志写入临时文件 | `false` |
| `CAM_SIGINT_MODE` | SIGINT 处理方式（`cancel`/`exit`/`cancel_then_exit`） | `cancel` |
| `CAM_SIGINT_DOUBLE_TAP_WINDOW` | 双击退出窗口时间（秒） | `1.0` |

## 工具

### codex

调用 OpenAI Codex CLI 代理，用于深度代码分析和审查。

**最适合**：代码审查、Bug 排查、安全分析

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `prompt` | string | ✓ | - | 任务指令 |
| `workspace` | string | ✓ | - | 项目目录的绝对路径 |
| `continuation_id` | string | | `""` | 传入上次响应中的 ID 以继续对话 |
| `permission` | string | | `read-only` | 权限级别：`read-only`、`workspace-write`、`unlimited` |
| `model` | string | | `""` | 模型覆盖（仅在明确请求时指定） |
| `save_file` | string | | `""` | 将代理输出保存到文件路径 |
| `save_file_with_prompt` | boolean | | `false` | 注入提示词引导模型输出详细思维过程 |
| `save_file_with_wrapper` | boolean | | `false` | 用 `<agent-output>` XML 标签包裹输出 |
| `save_file_with_append_mode` | boolean | | `false` | 追加到文件而非覆盖 |
| `full_output` | boolean | | `false` | 返回包含推理过程的详细输出 |
| `context_paths` | array | | `[]` | 提供上下文的参考文件/目录路径 |
| `image` | array | | `[]` | 用于视觉上下文的图片文件绝对路径 |
| `task_note` | string | | `""` | GUI 显示标签 |
| `debug` | boolean | | (全局) | 覆盖此次调用的调试设置 |

### gemini

调用 Google Gemini CLI 代理，用于 UI 设计和综合分析。

**最适合**：UI 原型、图片分析、需求发现、全文分析

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `prompt` | string | ✓ | - | 任务指令 |
| `workspace` | string | ✓ | - | 项目目录的绝对路径 |
| `continuation_id` | string | | `""` | 传入上次响应中的 ID 以继续对话 |
| `permission` | string | | `read-only` | 权限级别：`read-only`、`workspace-write`、`unlimited` |
| `model` | string | | `""` | 模型覆盖 |
| `save_file` | string | | `""` | 将代理输出保存到文件路径 |
| `save_file_with_prompt` | boolean | | `false` | 注入提示词引导模型输出详细思维过程 |
| `save_file_with_wrapper` | boolean | | `false` | 用 `<agent-output>` XML 标签包裹输出 |
| `save_file_with_append_mode` | boolean | | `false` | 追加到文件而非覆盖 |
| `full_output` | boolean | | `false` | 返回包含推理过程的详细输出 |
| `context_paths` | array | | `[]` | 提供上下文的参考文件/目录路径 |
| `task_note` | string | | `""` | GUI 显示标签 |
| `debug` | boolean | | (全局) | 覆盖此次调用的调试设置 |

### claude

调用 Anthropic Claude CLI 代理，用于代码实现。

**最适合**：功能实现、重构、代码生成

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `prompt` | string | ✓ | - | 任务指令 |
| `workspace` | string | ✓ | - | 项目目录的绝对路径 |
| `continuation_id` | string | | `""` | 传入上次响应中的 ID 以继续对话 |
| `permission` | string | | `read-only` | 权限级别：`read-only`、`workspace-write`、`unlimited` |
| `model` | string | | `""` | 模型覆盖（`sonnet`、`opus` 或完整模型名） |
| `save_file` | string | | `""` | 将代理输出保存到文件路径 |
| `save_file_with_prompt` | boolean | | `false` | 注入提示词引导模型输出详细思维过程 |
| `save_file_with_wrapper` | boolean | | `false` | 用 `<agent-output>` XML 标签包裹输出 |
| `save_file_with_append_mode` | boolean | | `false` | 追加到文件而非覆盖 |
| `full_output` | boolean | | `false` | 返回包含推理过程的详细输出 |
| `context_paths` | array | | `[]` | 提供上下文的参考文件/目录路径 |
| `system_prompt` | string | | `""` | 完全替换默认系统提示 |
| `append_system_prompt` | string | | `""` | 追加到默认提示的额外指令 |
| `agent` | string | | `""` | 指定代理名称（覆盖默认代理设置） |
| `task_note` | string | | `""` | GUI 显示标签 |
| `debug` | boolean | | (全局) | 覆盖此次调用的调试设置 |

### opencode

调用 OpenCode CLI 代理，用于全栈开发。

**最适合**：快速原型、多框架项目

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `prompt` | string | ✓ | - | 任务指令 |
| `workspace` | string | ✓ | - | 项目目录的绝对路径 |
| `continuation_id` | string | | `""` | 传入上次响应中的 ID 以继续对话 |
| `permission` | string | | `read-only` | 权限级别：`read-only`、`workspace-write`、`unlimited` |
| `model` | string | | `""` | 模型覆盖（格式：`provider/model`） |
| `save_file` | string | | `""` | 将代理输出保存到文件路径 |
| `save_file_with_prompt` | boolean | | `false` | 注入提示词引导模型输出详细思维过程 |
| `save_file_with_wrapper` | boolean | | `false` | 用 `<agent-output>` XML 标签包裹输出 |
| `save_file_with_append_mode` | boolean | | `false` | 追加到文件而非覆盖 |
| `full_output` | boolean | | `false` | 返回包含推理过程的详细输出 |
| `context_paths` | array | | `[]` | 提供上下文的参考文件/目录路径 |
| `file` | array | | `[]` | 要附加的文件绝对路径 |
| `agent` | string | | `build` | 代理类型：`build`、`plan` 等 |
| `task_note` | string | | `""` | GUI 显示标签 |
| `debug` | boolean | | (全局) | 覆盖此次调用的调试设置 |

## 提示词注入

部分参数会自动向提示词注入额外内容：

### `save_file_with_prompt`

当同时设置 `save_file` 和 `save_file_with_prompt` 时，会追加说明：

```
<你的提示词>

---
Note: Your response will be automatically saved to an external file.
Please verbalize your analysis process and insights in detail as you work...
```

### `context_paths`

当提供 `context_paths` 时，会追加参考路径：

```
<你的提示词>

---
Reference Paths:
- /src/api/handlers.py
- /config/settings.json
```

## 文件输出选项

### `save_file_with_wrapper`

启用时，输出会被 XML 标签包裹，包含元数据：

```
<agent-output agent="gemini" continuation_id="abc123">
... agent 响应 ...
</agent-output>
```

### `save_file_with_append_mode`

启用时，新输出追加到现有文件而非覆盖。配合 `save_file_with_wrapper` 使用，可实现多 agent 协作：

```
<agent-output agent="codex" continuation_id="...">
代码库的批判性分析...
</agent-output>

<agent-output agent="gemini" continuation_id="...">
改进的创意建议...
</agent-output>

<agent-output agent="claude" continuation_id="...">
实现总结...
</agent-output>
```

## 权限级别

| 级别 | 说明 | Codex | Claude | OpenCode |
|------|------|-------|--------|----------|
| `read-only` | 只能读取文件 | `--sandbox read-only` | `--tools Read,Grep,Glob` | `edit: deny, bash: deny` |
| `workspace-write` | 可在工作区内修改文件 | `--sandbox workspace-write` | `--tools Read,Edit,Write,Bash` | `edit: allow, bash: ask` |
| `unlimited` | 完全系统访问（谨慎使用） | `--sandbox danger-full-access` | `--tools default` | `edit: allow, bash: allow` |

## 调试模式

启用调试模式以获取详细的执行信息：

```bash
# 在响应中启用调试信息
export CAM_DEBUG=true

# 启用详细日志文件
export CAM_LOG_DEBUG=true
```

当 `CAM_LOG_DEBUG=true` 时，日志写入：
```
/tmp/cli-agent-mcp/cam_debug_YYYYMMDD_HHMMSS.log
```

调试输出包括：
- 完整的子进程命令
- 完整的 stdout/stderr 输出
- 返回码
- MCP 请求/响应摘要

## MCP 配置

添加到你的 MCP 客户端配置（例如 Claude Desktop 的 `claude_desktop_config.json`）：

### 基本配置

```json
{
  "mcpServers": {
    "cli-agent-mcp": {
      "command": "uvx",
      "args": ["cli-agent-mcp"]
    }
  }
}
```

### 从 GitHub 安装

```json
{
  "mcpServers": {
    "cli-agent-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/shiharuharu/cli-agent-mcp.git",
        "cli-agent-mcp"
      ]
    }
  }
}
```

### 启用调试模式

```json
{
  "mcpServers": {
    "cli-agent-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/shiharuharu/cli-agent-mcp.git",
        "cli-agent-mcp"
      ],
      "env": {
        "CAM_DEBUG": "true",
        "CAM_LOG_DEBUG": "true"
      }
    }
  }
}
```

### 禁用 GUI

```json
{
  "mcpServers": {
    "cli-agent-mcp": {
      "command": "uvx",
      "args": ["cli-agent-mcp"],
      "env": {
        "CAM_GUI": "false"
      }
    }
  }
}
```

### 限制可用工具

```json
{
  "mcpServers": {
    "cli-agent-mcp": {
      "command": "uvx",
      "args": ["cli-agent-mcp"],
      "env": {
        "CAM_TOOLS": "claude,gemini"
      }
    }
  }
}
```

## 项目结构

```
cli-agent-mcp/
├── shared/                  # 真相源（用于分发）
│   ├── gui/
│   ├── invokers/
│   └── parsers/
├── src/cli_agent_mcp/       # 主包
│   ├── shared/              # ← 同步副本（勿直接编辑）
│   ├── server.py
│   ├── config.py
│   └── gui_manager.py
├── tests/
└── shared_sync.sh
```

**重要**：永远不要直接编辑 `src/cli_agent_mcp/shared/`。始终编辑 `shared/` 然后运行同步脚本。

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 同步共享模块（先运行测试）
./shared_sync.sh
```

## 许可证

MIT
