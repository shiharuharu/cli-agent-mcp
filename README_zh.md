# cli-agent-mcp

[English](README.md)

统一的 MCP（Model Context Protocol）服务器，用于 CLI AI 代理。提供单一接口调用 Codex、Gemini、Claude、OpenCode CLI 工具和 Nano Banana Pro 图片生成。

## 为什么选择 cli-agent-mcp？

这不只是 CLI 的封装 —— 这是一种**多模型协作的调度模式**。

**说不清楚需求？** 让 Claude 来调度。描述你想要什么，它会把模糊的想法分解成具体的任务，分配给合适的 agent。委派的过程本身就在迫使你理清思路。

**规划宏大的产品愿景？** 每个模型带来独特的视角：
- **Codex**：批评家。锐利的分析目光捕捉你遗漏的细节，挑战假设，发现边界情况。
- **Gemini**：创意者。发散思维，意想不到的连接，那些你不知道自己需要的灵感火花。
- **Claude**：书记员。忠实执行，清晰文档，把想法变成可运行的代码。
- **Banana**：艺术家。高保真图片生成，用于 UI 原型、产品视觉和创意资产。

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
| `CAM_ENABLE` | 启用的工具列表，逗号分隔（空=全部） | `""`（全部） |
| `CAM_DISABLE` | 禁用的工具列表，逗号分隔（从 enable 中减去） | `""` |
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
| `save_file` | string | | `""` | 大输出首选。直接写入文件，避免上下文溢出 |
| `report_mode` | boolean | | `false` | 生成独立报告格式 |
| `save_file_with_wrapper` | boolean | | `false` | 用 `<agent-output>` XML 标签包裹输出 |
| `save_file_with_append_mode` | boolean | | `false` | 追加到文件而非覆盖 |
| `verbose_output` | boolean | | `false` | 返回包含推理过程的详细输出 |
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
| `save_file` | string | | `""` | 大输出首选。直接写入文件，避免上下文溢出 |
| `report_mode` | boolean | | `false` | 生成独立报告格式 |
| `save_file_with_wrapper` | boolean | | `false` | 用 `<agent-output>` XML 标签包裹输出 |
| `save_file_with_append_mode` | boolean | | `false` | 追加到文件而非覆盖 |
| `verbose_output` | boolean | | `false` | 返回包含推理过程的详细输出 |
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
| `save_file` | string | | `""` | 大输出首选。直接写入文件，避免上下文溢出 |
| `report_mode` | boolean | | `false` | 生成独立报告格式 |
| `save_file_with_wrapper` | boolean | | `false` | 用 `<agent-output>` XML 标签包裹输出 |
| `save_file_with_append_mode` | boolean | | `false` | 追加到文件而非覆盖 |
| `verbose_output` | boolean | | `false` | 返回包含推理过程的详细输出 |
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
| `save_file` | string | | `""` | 大输出首选。直接写入文件，避免上下文溢出 |
| `report_mode` | boolean | | `false` | 生成独立报告格式 |
| `save_file_with_wrapper` | boolean | | `false` | 用 `<agent-output>` XML 标签包裹输出 |
| `save_file_with_append_mode` | boolean | | `false` | 追加到文件而非覆盖 |
| `verbose_output` | boolean | | `false` | 返回包含推理过程的详细输出 |
| `context_paths` | array | | `[]` | 提供上下文的参考文件/目录路径 |
| `file` | array | | `[]` | 要附加的文件绝对路径 |
| `agent` | string | | `build` | 代理类型：`build`、`plan` 等 |
| `task_note` | string | | `""` | GUI 显示标签 |
| `debug` | boolean | | (全局) | 覆盖此次调用的调试设置 |

### banana

通过 Nano Banana Pro API 生成高保真图片。

**最适合**：UI 原型、产品视觉、信息图、建筑效果图、角色艺术

Nano Banana Pro 拥有卓越的理解能力和视觉表达能力——你的提示词创意才是唯一的限制，而不是模型。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `prompt` | string | ✓ | - | 图片生成提示词 |
| `save_path` | string | ✓ | - | 图片保存的基础目录 |
| `task_note` | string | ✓ | - | 子目录名称（建议英文，如 'hero-banner'）。文件保存到 `{save_path}/{task_note}/` |
| `images` | array | | `[]` | 参考图片（绝对路径），可选 role 和 label |
| `aspect_ratio` | string | | `"1:1"` | 图片比例：`1:1`、`2:3`、`3:2`、`3:4`、`4:3`、`4:5`、`5:4`、`9:16`、`16:9`、`21:9` |
| `resolution` | string | | `"1K"` | 图片分辨率：`1K`、`2K`、`4K` |
| `include_thoughts` | boolean | | `false` | 在响应中包含思维过程 |

**环境变量：**

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `BANANA_AUTH_TOKEN` | ✓ | - | Google API 密钥或 Bearer 令牌 |
| `BANANA_ENDPOINT` | | `https://generativelanguage.googleapis.com` | API 端点（版本路径自动补全） |

**提示词最佳实践：**
- 明确请求图片（如以 "Generate an image:" 开头或包含 `"output":"image"`）
- 复杂请求使用结构化规格（JSON / XML 标签 / 标签分区）
- 使用 `MUST/STRICT/CRITICAL` 标记不可协商的约束
- 添加负面约束（如 "no watermark"、"no distorted hands"）

### image

通过 OpenRouter 兼容或 OpenAI 兼容端点生成图片。

**最适合**：需要兼容多种提供商的通用图片生成。如需使用 Gemini 模型获得最佳效果，请使用 `banana` 工具。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `prompt` | string | ✓ | - | 图片生成提示词 |
| `save_path` | string | ✓ | - | 图片保存的基础目录 |
| `task_note` | string | ✓ | - | 子目录名称（建议英文，如 'hero-banner'）。文件保存到 `{save_path}/{task_note}/` |
| `images` | array | | `[]` | 参考图片（绝对路径），可选 role 和 label |
| `aspect_ratio` | string | | `"1:1"` | 图片比例：`1:1`、`2:3`、`3:2`、`3:4`、`4:3`、`4:5`、`5:4`、`9:16`、`16:9`、`21:9` |
| `resolution` | string | | `"1K"` | 图片分辨率：`1K`、`2K`、`4K` |
| `model` | string | | (env) | 用于生成的模型 |
| `api_format` | string | | `"auto"` | API 格式：`auto`、`openrouter_chat`、`openai_images`、`openai_responses` |

**环境变量：**

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `IMAGE_AUTH_TOKEN` | ✓ | - | 图片生成 API 密钥 |
| `IMAGE_ENDPOINT` | | `https://openrouter.ai/api` | API 端点（版本路径自动补全） |
| `IMAGE_MODEL` | | `gpt-image-1` | 默认模型 |
| `IMAGE_API_FORMAT` | | `openrouter_chat` | API 格式：`openrouter_chat`、`openai_images`、`openai_responses` |

### get_gui_url

获取 GUI 仪表盘 URL。返回实时事件查看器的 HTTP URL。

无需参数。

## 提示词注入

部分参数会自动向提示词注入额外内容，使用 `<mcp-injection>` XML 标签。这些标签便于调试和定位系统注入的内容。

### `report_mode`

当同时设置 `save_file` 和 `report_mode` 时，会注入输出格式要求：

```xml
<你的提示词>

<mcp-injection type="output-format">
  <output-requirements>
    <rule>This response will be saved as a standalone document.</rule>
    <rule>Write so it can be understood WITHOUT any prior conversation context.</rule>
    <rule>Do NOT reference "above", "previous messages", or "as discussed".</rule>
    <rule>Use the same language as the user's request.</rule>
  </output-requirements>
  <structure>
    <section name="Summary">3-7 bullet points with key findings and conclusions</section>
    <section name="Context">Restate the task/problem so readers understand without chat history</section>
    <section name="Analysis">Step-by-step reasoning with evidence; include file:line references</section>
    <section name="Recommendations">Actionable next steps ordered by priority</section>
  </structure>
  <note>Write with enough detail to be useful standalone, but avoid unnecessary filler.</note>
</mcp-injection>
```

### `context_paths`

当提供 `context_paths` 时，会注入参考路径：

```xml
<你的提示词>

<mcp-injection type="reference-paths">
  <description>
    These paths are provided as reference for project structure.
    You may use them to understand naming conventions and file organization.
  </description>
  <paths>
    <path>/src/api/handlers.py</path>
    <path>/config/settings.json</path>
  </paths>
</mcp-injection>
```

## 无状态设计

**重要**：每次工具调用都是无状态的 - agent 没有之前调用的记忆。

- **新对话**（无 `continuation_id`）：在提示词中包含所有相关上下文 - 背景、具体细节、约束条件和之前的发现。
- **继续对话**（有 `continuation_id`）：agent 保留该会话的上下文，所以可以简洁描述。

如果你的请求引用了之前的上下文（如"修复那个 bug"、"继续之前的工作"），你必须：
1. 提供之前响应中的 `continuation_id`，或
2. 将引用展开为具体细节

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

## 响应格式

所有响应都使用 XML 格式包装：

### 成功响应

```xml
<response>
  <thought_process>...</thought_process>  <!-- 仅当 verbose_output=true -->
  <answer>
    代理的响应内容...
  </answer>
  <continuation_id>session-id-here</continuation_id>
  <debug_info>...</debug_info>  <!-- 仅当 debug=true -->
</response>
```

### 错误响应

错误响应包含部分进度以便重试：

```xml
<response>
  <error>错误信息</error>
  <thought_process>...</thought_process>  <!-- 错误前收集的步骤 -->
  <partial_answer>...</partial_answer>    <!-- 部分输出（如有） -->
  <continuation_id>session-id</continuation_id>
  <hint>Task failed. Above is the output collected so far. You can send 'continue' with this continuation_id to retry.</hint>
  <debug_info>...</debug_info>
</response>
```

## 权限级别

| 级别 | 说明 | Codex | Gemini | Claude | OpenCode | Banana |
|------|------|-------|--------|--------|----------|--------|
| `read-only` | 只能读取文件 | `--sandbox read-only` | 仅只读工具 | `--tools Read,Grep,Glob` | `edit: deny, bash: deny` | 仅读取 workspace 内图片 |
| `workspace-write` | 可在工作区内修改文件 | `--sandbox workspace-write` | 全部工具 + sandbox | `--tools Read,Edit,Write,Bash` | `edit: allow, bash: ask` | 仅写入 workspace |
| `unlimited` | 完全系统访问（谨慎使用） | `--sandbox danger-full-access` | 全部工具，无 sandbox | `--tools default` | `edit: allow, bash: allow` | 完全访问 |

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
        "CAM_ENABLE": "claude,gemini"
      }
    }
  }
}
```

### 禁用图片工具

```json
{
  "mcpServers": {
    "cli-agent-mcp": {
      "command": "uvx",
      "args": ["cli-agent-mcp"],
      "env": {
        "CAM_DISABLE": "banana,image"
      }
    }
  }
}
```

## 项目结构

```
cli-agent-mcp/
├── src/cli_agent_mcp/
│   ├── __init__.py          # 包导出
│   ├── __main__.py          # 入口点
│   ├── app.py               # 服务器生命周期 (run_server, main)
│   ├── server.py            # MCP 协议适配器 (create_server)
│   ├── tool_schema.py       # 工具描述和 JSON Schema
│   ├── config.py            # 配置管理
│   ├── gui_manager.py       # GUI 仪表盘管理器
│   ├── orchestrator.py      # 请求注册表
│   ├── signal_manager.py    # 信号处理 (SIGINT/SIGTERM)
│   ├── handlers/            # 工具处理器
│   │   ├── base.py          # ToolContext, ToolHandler 基类
│   │   ├── cli.py           # CLI 工具 (codex/gemini/claude/opencode)
│   │   ├── parallel.py      # 并行执行 (*_parallel 工具)
│   │   └── image_tools.py   # 图片工具 (banana/image)
│   ├── utils/               # 工具函数
│   │   ├── xml_wrapper.py   # XML 转义和包装构建
│   │   └── prompt_injection.py  # 提示词注入辅助
│   └── shared/              # 共享模块
│       ├── invokers/        # CLI 调用器实现
│       ├── parsers/         # 输出解析器
│       ├── gui/             # GUI 组件
│       └── response_formatter.py  # 响应格式化
└── tests/
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest
```

## 许可证

MIT
