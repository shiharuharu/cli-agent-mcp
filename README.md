# cli-agent-mcp

[中文文档](README_zh.md)

Unified MCP (Model Context Protocol) server for CLI AI agents. Provides a single interface to invoke Codex, Gemini, Claude, and OpenCode CLI tools.

## Why cli-agent-mcp?

This is more than a CLI wrapper — it's an **orchestration pattern** for multi-model collaboration.

**Can't articulate your requirements clearly?** Let Claude orchestrate. Describe what you want, and it will decompose your vague idea into concrete tasks for the right agent. The act of delegation forces clarity.

**Planning a grand product vision?** Each model brings a unique lens:
- **Codex**: The critic. Its analytical eye catches what you missed, challenges assumptions, finds edge cases.
- **Gemini**: The creative. Divergent thinking, unexpected connections, the spark you didn't know you needed.
- **Claude**: The scribe. Faithful execution, clear documentation, turning ideas into working code.

**Want persistent results?** Use `save_file` to capture agent outputs, then let Claude synthesize insights across multiple analyses.

We don't just wrap CLIs — we provide a **thinking framework** for human-AI collaboration.

## Features

- **Unified Interface**: Single MCP server exposing multiple CLI agents
- **GUI Dashboard**: Real-time task monitoring with pywebview
- **Request Isolation**: Per-request execution context for safe concurrent usage
- **Signal Handling**: Graceful cancellation via SIGINT without killing the server
- **Debug Logging**: Comprehensive subprocess output capture for debugging

## Screenshot

![CLI Agent MCP GUI](dev-docs/screenshot/screenshot.png)

## Installation

```bash
# Install from PyPI (when published)
uvx cli-agent-mcp

# Install from GitHub
uvx --from git+https://github.com/shiharuharu/cli-agent-mcp.git cli-agent-mcp

# Install from source (editable mode for development)
uvx --from /path/to/cli-agent-mcp cli-agent-mcp

# Or use pip
pip install -e .
```

## Configuration

Configure via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `CAM_TOOLS` | Comma-separated list of allowed tools (empty = all) | `""` (all) |
| `CAM_GUI` | Enable GUI dashboard | `true` |
| `CAM_GUI_DETAIL` | GUI detail mode | `false` |
| `CAM_GUI_KEEP` | Keep GUI on exit | `false` |
| `CAM_DEBUG` | Include debug info in MCP responses | `false` |
| `CAM_LOG_DEBUG` | Write debug logs to temp file | `false` |
| `CAM_SIGINT_MODE` | SIGINT handling (`cancel`/`exit`/`cancel_then_exit`) | `cancel` |
| `CAM_SIGINT_DOUBLE_TAP_WINDOW` | Double-tap exit window (seconds) | `1.0` |

## Tools

### codex

Invoke OpenAI Codex CLI agent for deep code analysis and critical review.

**Best for**: Code review, bug hunting, security analysis

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `prompt` | string | ✓ | - | Task instruction for the agent |
| `workspace` | string | ✓ | - | Absolute path to the project directory |
| `continuation_id` | string | | `""` | Pass from previous response to continue conversation |
| `permission` | string | | `read-only` | Permission level: `read-only`, `workspace-write`, `unlimited` |
| `model` | string | | `""` | Model override (only specify if explicitly requested) |
| `save_file` | string | | `""` | Save agent output to file path |
| `save_file_with_prompt` | boolean | | `false` | Inject prompt hint to encourage verbose reasoning output |
| `save_file_with_wrapper` | boolean | | `false` | Wrap output with `<agent-output>` XML tags |
| `save_file_with_append_mode` | boolean | | `false` | Append to file instead of overwriting |
| `full_output` | boolean | | `false` | Return detailed output including reasoning |
| `context_paths` | array | | `[]` | Reference file/directory paths to provide context |
| `image` | array | | `[]` | Absolute paths to image files for visual context |
| `task_note` | string | | `""` | Display label for GUI |
| `debug` | boolean | | (global) | Override debug setting for this call |

### gemini

Invoke Google Gemini CLI agent for UI design and comprehensive analysis.

**Best for**: UI mockups, image analysis, requirement discovery, full-text analysis

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `prompt` | string | ✓ | - | Task instruction for the agent |
| `workspace` | string | ✓ | - | Absolute path to the project directory |
| `continuation_id` | string | | `""` | Pass from previous response to continue conversation |
| `permission` | string | | `read-only` | Permission level: `read-only`, `workspace-write`, `unlimited` |
| `model` | string | | `""` | Model override |
| `save_file` | string | | `""` | Save agent output to file path |
| `save_file_with_prompt` | boolean | | `false` | Inject prompt hint to encourage verbose reasoning output |
| `save_file_with_wrapper` | boolean | | `false` | Wrap output with `<agent-output>` XML tags |
| `save_file_with_append_mode` | boolean | | `false` | Append to file instead of overwriting |
| `full_output` | boolean | | `false` | Return detailed output including reasoning |
| `context_paths` | array | | `[]` | Reference file/directory paths to provide context |
| `task_note` | string | | `""` | Display label for GUI |
| `debug` | boolean | | (global) | Override debug setting for this call |

### claude

Invoke Anthropic Claude CLI agent for code implementation.

**Best for**: Feature implementation, refactoring, code generation

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `prompt` | string | ✓ | - | Task instruction for the agent |
| `workspace` | string | ✓ | - | Absolute path to the project directory |
| `continuation_id` | string | | `""` | Pass from previous response to continue conversation |
| `permission` | string | | `read-only` | Permission level: `read-only`, `workspace-write`, `unlimited` |
| `model` | string | | `""` | Model override (`sonnet`, `opus`, or full model name) |
| `save_file` | string | | `""` | Save agent output to file path |
| `save_file_with_prompt` | boolean | | `false` | Inject prompt hint to encourage verbose reasoning output |
| `save_file_with_wrapper` | boolean | | `false` | Wrap output with `<agent-output>` XML tags |
| `save_file_with_append_mode` | boolean | | `false` | Append to file instead of overwriting |
| `full_output` | boolean | | `false` | Return detailed output including reasoning |
| `context_paths` | array | | `[]` | Reference file/directory paths to provide context |
| `system_prompt` | string | | `""` | Complete replacement for the default system prompt |
| `append_system_prompt` | string | | `""` | Additional instructions appended to default prompt |
| `agent` | string | | `""` | Specify agent name (overrides default agent setting) |
| `task_note` | string | | `""` | Display label for GUI |
| `debug` | boolean | | (global) | Override debug setting for this call |

### opencode

Invoke OpenCode CLI agent for full-stack development.

**Best for**: Rapid prototyping, multi-framework projects

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `prompt` | string | ✓ | - | Task instruction for the agent |
| `workspace` | string | ✓ | - | Absolute path to the project directory |
| `continuation_id` | string | | `""` | Pass from previous response to continue conversation |
| `permission` | string | | `read-only` | Permission level: `read-only`, `workspace-write`, `unlimited` |
| `model` | string | | `""` | Model override (format: `provider/model`) |
| `save_file` | string | | `""` | Save agent output to file path |
| `save_file_with_prompt` | boolean | | `false` | Inject prompt hint to encourage verbose reasoning output |
| `save_file_with_wrapper` | boolean | | `false` | Wrap output with `<agent-output>` XML tags |
| `save_file_with_append_mode` | boolean | | `false` | Append to file instead of overwriting |
| `full_output` | boolean | | `false` | Return detailed output including reasoning |
| `context_paths` | array | | `[]` | Reference file/directory paths to provide context |
| `file` | array | | `[]` | Absolute paths to files to attach |
| `agent` | string | | `build` | Agent type: `build`, `plan`, etc. |
| `task_note` | string | | `""` | Display label for GUI |
| `debug` | boolean | | (global) | Override debug setting for this call |

## Prompt Injection

Some parameters automatically inject additional content into the prompt:

### `save_file_with_prompt`

When `save_file` and `save_file_with_prompt` are both set, a note is appended:

```
<your prompt>

---
Note: Your response will be automatically saved to an external file.
Please verbalize your analysis process and insights in detail as you work...
```

### `context_paths`

When `context_paths` is provided, reference paths are appended:

```
<your prompt>

---
Reference Paths:
- /src/api/handlers.py
- /config/settings.json
```

## File Output Options

### `save_file_with_wrapper`

When enabled, output is wrapped with XML tags containing metadata:

```
<agent-output agent="gemini" continuation_id="abc123">
... agent response ...
</agent-output>
```

### `save_file_with_append_mode`

When enabled, new output is appended to existing file instead of overwriting. Combined with `save_file_with_wrapper`, enables multi-agent collaboration:

```
<agent-output agent="codex" continuation_id="...">
Critical analysis of the codebase...
</agent-output>

<agent-output agent="gemini" continuation_id="...">
Creative suggestions for improvement...
</agent-output>

<agent-output agent="claude" continuation_id="...">
Implementation summary...
</agent-output>
```

## Permission Levels

| Level | Description | Codex | Claude | OpenCode |
|-------|-------------|-------|--------|----------|
| `read-only` | Can only read files | `--sandbox read-only` | `--tools Read,Grep,Glob` | `edit: deny, bash: deny` |
| `workspace-write` | Can modify files within workspace | `--sandbox workspace-write` | `--tools Read,Edit,Write,Bash` | `edit: allow, bash: ask` |
| `unlimited` | Full system access (use with caution) | `--sandbox danger-full-access` | `--tools default` | `edit: allow, bash: allow` |

## Debug Mode

Enable debug mode to get detailed execution information:

```bash
# Enable debug info in responses
export CAM_DEBUG=true

# Enable detailed log file
export CAM_LOG_DEBUG=true
```

When `CAM_LOG_DEBUG=true`, logs are written to:
```
/tmp/cli-agent-mcp/cam_debug_YYYYMMDD_HHMMSS.log
```

Debug output includes:
- Full subprocess command
- Complete stdout/stderr output
- Return codes
- MCP request/response summaries

## MCP Configuration

Add to your MCP client configuration (e.g., Claude Desktop `claude_desktop_config.json`):

### Basic Configuration

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

### Install from GitHub

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

### With Debug Mode

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

### Disable GUI

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

### Limit Available Tools

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

## Project Structure

```
cli-agent-mcp/
├── shared/                  # Source of truth (for distribution)
│   ├── gui/
│   ├── invokers/
│   └── parsers/
├── src/cli_agent_mcp/       # Main package
│   ├── shared/              # ← Synced copy (do not edit directly)
│   ├── server.py
│   ├── config.py
│   └── gui_manager.py
├── tests/
└── shared_sync.sh
```

**Important**: Never edit `src/cli_agent_mcp/shared/` directly. Always edit `shared/` and run the sync script.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Sync shared modules (runs tests first)
./shared_sync.sh
```

## License

MIT
