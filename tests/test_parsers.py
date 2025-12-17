"""解析器模块测试。

使用真实样本数据验证 Gemini、Codex 和 Claude 解析器。
"""

from __future__ import annotations

import pytest

from parsers import (
    CLISource,
    ClaudeParser,
    CodexParser,
    ContentType,
    EventCategory,
    GeminiParser,
    LifecycleEvent,
    MessageEvent,
    OperationEvent,
    OperationType,
    Status,
    SystemEvent,
    create_parser,
    detect_source,
    parse_event,
    parse_events,
)


class TestDetectSource:
    """测试来源检测。"""

    def test_detect_gemini_init(self):
        """检测 Gemini init 事件。"""
        data = {"type": "init", "session_id": "abc123", "model": "gemini-3"}
        assert detect_source(data) == CLISource.GEMINI

    def test_detect_gemini_message(self):
        """检测 Gemini message 事件。"""
        data = {"type": "message", "role": "assistant", "content": "Hello"}
        assert detect_source(data) == CLISource.GEMINI

    def test_detect_codex_thread(self):
        """检测 Codex thread.started 事件。"""
        data = {"type": "thread.started", "thread_id": "123"}
        assert detect_source(data) == CLISource.CODEX

    def test_detect_codex_item(self):
        """检测 Codex item.* 事件。"""
        data = {"type": "item.completed", "item": {"type": "agent_message"}}
        assert detect_source(data) == CLISource.CODEX

    def test_detect_unknown(self):
        """未知来源返回 UNKNOWN。"""
        data = {"type": "some_unknown_type"}
        assert detect_source(data) == CLISource.UNKNOWN

    def test_detect_claude_init(self):
        """检测 Claude system/init 事件。"""
        data = {
            "type": "system",
            "subtype": "init",
            "session_id": "abc123",
            "claude_code_version": "2.0.69",
        }
        assert detect_source(data) == CLISource.CLAUDE

    def test_detect_claude_assistant(self):
        """检测 Claude assistant 事件。"""
        data = {
            "type": "assistant",
            "message": {"content": []},
            "session_id": "abc123",
        }
        assert detect_source(data) == CLISource.CLAUDE

    def test_detect_claude_result(self):
        """检测 Claude result 事件。"""
        data = {
            "type": "result",
            "subtype": "success",
            "session_id": "abc123",
        }
        assert detect_source(data) == CLISource.CLAUDE


class TestGeminiParser:
    """测试 Gemini 解析器。"""

    def test_parse_init(self):
        """解析 init 事件。"""
        parser = GeminiParser()
        data = {
            "type": "init",
            "timestamp": "2025-12-16T05:41:16.835Z",
            "session_id": "d6336abb-88c7-496e-bec4-adca188152b4",
            "model": "gemini-3-pro-preview",
        }
        event = parser.parse(data)

        assert isinstance(event, LifecycleEvent)
        assert event.category == EventCategory.LIFECYCLE
        assert event.lifecycle_type == "session_start"
        assert event.session_id == "d6336abb-88c7-496e-bec4-adca188152b4"
        assert event.model == "gemini-3-pro-preview"
        assert event.source == CLISource.GEMINI

    def test_parse_user_message(self):
        """解析用户消息。"""
        parser = GeminiParser()
        data = {
            "type": "message",
            "timestamp": "2025-12-16T05:41:16.835Z",
            "role": "user",
            "content": "Say hello",
        }
        event = parser.parse(data)

        assert isinstance(event, MessageEvent)
        assert event.category == EventCategory.MESSAGE
        assert event.role == "user"
        assert event.text == "Say hello"
        assert event.content_type == ContentType.TEXT

    def test_parse_assistant_message(self):
        """解析助手消息。"""
        parser = GeminiParser()
        data = {
            "type": "message",
            "timestamp": "2025-12-16T05:41:33.842Z",
            "role": "assistant",
            "content": "Hello! I am Gemini.",
            "delta": True,
        }
        event = parser.parse(data)

        assert isinstance(event, MessageEvent)
        assert event.role == "assistant"
        assert event.text == "Hello! I am Gemini."
        assert event.is_delta is True

    def test_parse_tool_use(self):
        """解析 tool_use 事件。"""
        parser = GeminiParser()
        data = {
            "type": "tool_use",
            "timestamp": "2025-12-16T05:42:50.318Z",
            "tool_name": "list_directory",
            "tool_id": "list_directory-1765863770318-f3113670ca35d",
            "parameters": {"dir_path": "."},
        }
        event = parser.parse(data)

        assert isinstance(event, OperationEvent)
        assert event.category == EventCategory.OPERATION
        assert event.operation_type == OperationType.TOOL
        assert event.name == "list_directory"
        assert event.operation_id == "list_directory-1765863770318-f3113670ca35d"
        assert event.status == Status.RUNNING
        assert "dir_path" in event.input

    def test_parse_tool_result_success(self):
        """解析成功的 tool_result。"""
        parser = GeminiParser()
        # 先解析 tool_use 以缓存工具名
        parser.parse({
            "type": "tool_use",
            "tool_name": "list_directory",
            "tool_id": "tool-123",
            "parameters": {},
        })

        data = {
            "type": "tool_result",
            "timestamp": "2025-12-16T05:42:50.368Z",
            "tool_id": "tool-123",
            "status": "success",
            "output": "Listed 1 item(s).",
        }
        event = parser.parse(data)

        assert isinstance(event, OperationEvent)
        assert event.status == Status.SUCCESS
        assert event.output == "Listed 1 item(s)."
        assert event.name == "list_directory"

    def test_parse_error(self):
        """解析 error 事件。"""
        parser = GeminiParser()
        data = {
            "type": "error",
            "timestamp": "2025-12-16T05:42:51.025Z",
            "severity": "error",
            "message": "API Error occurred",
        }
        event = parser.parse(data)

        assert isinstance(event, SystemEvent)
        assert event.category == EventCategory.SYSTEM
        assert event.severity == "error"
        assert event.message == "API Error occurred"

    def test_parse_result(self):
        """解析 result 事件。"""
        parser = GeminiParser()
        data = {
            "type": "result",
            "timestamp": "2025-12-16T05:41:33.855Z",
            "status": "success",
            "stats": {
                "total_tokens": 6195,
                "input_tokens": 5846,
                "output_tokens": 31,
                "duration_ms": 17020,
                "tool_calls": 0,
            },
        }
        event = parser.parse(data)

        assert isinstance(event, LifecycleEvent)
        assert event.lifecycle_type == "session_end"
        assert event.status == Status.SUCCESS
        assert event.stats["total_tokens"] == 6195

    def test_parse_unknown_type_fallback(self):
        """未知类型应返回 Fallback 事件。"""
        parser = GeminiParser()
        data = {"type": "unknown_future_type", "data": "something"}
        event = parser.parse(data)

        assert isinstance(event, SystemEvent)
        assert event.is_fallback is True
        assert "unknown_future_type" in event.message

    def test_parse_sample_file(self, gemini_simple_greeting):
        """使用真实样本文件测试。"""
        parser = GeminiParser()
        events = gemini_simple_greeting.get("events", [])

        parsed_events = [parser.parse(e) for e in events]

        # 验证第一个是 init
        assert isinstance(parsed_events[0], LifecycleEvent)
        assert parsed_events[0].lifecycle_type == "session_start"

        # 验证最后一个是 result
        assert isinstance(parsed_events[-1], LifecycleEvent)
        assert parsed_events[-1].lifecycle_type == "session_end"

        # 验证中间有消息事件
        message_events = [e for e in parsed_events if isinstance(e, MessageEvent)]
        assert len(message_events) >= 1


class TestCodexParser:
    """测试 Codex 解析器。"""

    def test_parse_thread_started(self):
        """解析 thread.started 事件。"""
        parser = CodexParser()
        data = {
            "type": "thread.started",
            "thread_id": "019b25ad-271b-7d93-9738-9bf9e1fc817a",
        }
        event = parser.parse(data)

        assert isinstance(event, LifecycleEvent)
        assert event.lifecycle_type == "session_start"
        assert event.session_id == "019b25ad-271b-7d93-9738-9bf9e1fc817a"
        assert event.source == CLISource.CODEX

    def test_parse_turn_completed(self):
        """解析 turn.completed 事件。"""
        parser = CodexParser()
        data = {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 8867,
                "cached_input_tokens": 0,
                "output_tokens": 50,
            },
        }
        event = parser.parse(data)

        assert isinstance(event, LifecycleEvent)
        assert event.lifecycle_type == "turn_end"
        assert event.status == Status.SUCCESS
        assert event.stats["input_tokens"] == 8867

    def test_parse_agent_message(self):
        """解析 agent_message 项。"""
        parser = CodexParser()
        data = {
            "type": "item.completed",
            "item": {
                "id": "item_0",
                "type": "agent_message",
                "text": "Hello! I'm GPT-5.2 running in the Codex CLI.",
            },
        }
        event = parser.parse(data)

        assert isinstance(event, MessageEvent)
        assert event.role == "assistant"
        assert event.content_type == ContentType.TEXT
        assert "GPT-5.2" in event.text

    def test_parse_reasoning(self):
        """解析 reasoning 项。"""
        parser = CodexParser()
        data = {
            "type": "item.completed",
            "item": {
                "id": "item_0",
                "type": "reasoning",
                "text": "**Preparing to list files**\nI'll use shell commands...",
            },
        }
        event = parser.parse(data)

        assert isinstance(event, MessageEvent)
        assert event.content_type == ContentType.REASONING
        assert "Preparing to list files" in event.text

    def test_parse_command_execution(self):
        """解析 command_execution 项。"""
        parser = CodexParser()
        data = {
            "type": "item.completed",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "/bin/zsh -lc 'ls -la'",
                "aggregated_output": "total 16\ndrwxr-xr-x  3 user  staff    96",
                "exit_code": 0,
                "status": "completed",
            },
        }
        event = parser.parse(data)

        assert isinstance(event, OperationEvent)
        assert event.operation_type == OperationType.COMMAND
        assert "ls -la" in event.input
        assert event.status == Status.SUCCESS
        assert event.metadata["exit_code"] == 0

    def test_parse_command_in_progress(self):
        """解析进行中的命令。"""
        parser = CodexParser()
        data = {
            "type": "item.started",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "/bin/zsh -lc 'npm install'",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        }
        event = parser.parse(data)

        assert isinstance(event, OperationEvent)
        assert event.status == Status.RUNNING

    def test_parse_function_call_and_output(self):
        """解析 function_call 和 function_call_output。"""
        parser = CodexParser()

        # 先解析 function_call
        call_data = {
            "type": "item.completed",
            "item": {
                "id": "item_1",
                "type": "function_call",
                "name": "read_file",
                "call_id": "call_123",
                "arguments": '{"path": "/src/main.py"}',
            },
        }
        call_event = parser.parse(call_data)

        assert isinstance(call_event, OperationEvent)
        assert call_event.name == "read_file"
        assert call_event.operation_id == "call_123"
        assert call_event.status == Status.RUNNING

        # 再解析 function_call_output
        output_data = {
            "type": "item.completed",
            "item": {
                "id": "item_2",
                "type": "function_call_output",
                "call_id": "call_123",
                "output": "def main():\n    pass",
            },
        }
        output_event = parser.parse(output_data)

        assert isinstance(output_event, OperationEvent)
        assert output_event.name == "read_file"  # 从缓存获取
        assert output_event.status == Status.SUCCESS
        assert "def main()" in output_event.output

    def test_parse_unknown_item_type_fallback(self):
        """未知 item 类型应返回 Fallback。"""
        parser = CodexParser()
        data = {
            "type": "item.completed",
            "item": {
                "id": "item_0",
                "type": "future_unknown_type",
                "data": "something",
            },
        }
        event = parser.parse(data)

        assert isinstance(event, SystemEvent)
        assert event.is_fallback is True

    def test_parse_sample_file(self, codex_simple_greeting):
        """使用真实样本文件测试。"""
        parser = CodexParser()
        events = codex_simple_greeting.get("events", [])

        parsed_events = [parser.parse(e) for e in events]

        # 验证第一个是 thread.started
        assert isinstance(parsed_events[0], LifecycleEvent)
        assert parsed_events[0].lifecycle_type == "session_start"

        # 验证最后一个是 turn.completed
        assert isinstance(parsed_events[-1], LifecycleEvent)
        assert parsed_events[-1].lifecycle_type == "turn_end"

    def test_parse_code_analysis_sample(self, codex_code_analysis):
        """测试包含命令执行和推理的复杂样本。"""
        parser = CodexParser()
        events = codex_code_analysis.get("events", [])

        parsed_events = [parser.parse(e) for e in events]

        # 统计各类型事件
        lifecycle_count = sum(1 for e in parsed_events if isinstance(e, LifecycleEvent))
        message_count = sum(1 for e in parsed_events if isinstance(e, MessageEvent))
        operation_count = sum(1 for e in parsed_events if isinstance(e, OperationEvent))

        # 应该有生命周期事件（thread.started, turn.started, turn.completed）
        assert lifecycle_count >= 2

        # 应该有消息事件（agent_message, reasoning）
        assert message_count >= 1

        # 应该有操作事件（command_execution）
        assert operation_count >= 1


class TestConvenienceFunctions:
    """测试便捷函数。"""

    def test_parse_event_auto_detect_gemini(self):
        """parse_event 自动检测 Gemini。"""
        data = {"type": "init", "session_id": "abc", "model": "gemini"}
        event = parse_event(data)

        assert event.source == CLISource.GEMINI
        assert isinstance(event, LifecycleEvent)

    def test_parse_event_auto_detect_codex(self):
        """parse_event 自动检测 Codex。"""
        data = {"type": "thread.started", "thread_id": "123"}
        event = parse_event(data)

        assert event.source == CLISource.CODEX
        assert isinstance(event, LifecycleEvent)

    def test_create_parser_gemini(self):
        """create_parser 创建 Gemini 解析器。"""
        parser = create_parser("gemini")
        assert isinstance(parser, GeminiParser)

    def test_create_parser_codex(self):
        """create_parser 创建 Codex 解析器。"""
        parser = create_parser(CLISource.CODEX)
        assert isinstance(parser, CodexParser)

    def test_create_parser_invalid(self):
        """create_parser 对无效来源抛出异常。"""
        with pytest.raises(ValueError):
            create_parser("unknown")


class TestForwardCompatibility:
    """测试向前兼容性（处理未知字段）。"""

    def test_extra_fields_ignored_gemini(self):
        """Gemini 事件中的额外字段应被忽略。"""
        parser = GeminiParser()
        data = {
            "type": "init",
            "timestamp": "2025-12-16T05:41:16.835Z",
            "session_id": "abc123",
            "model": "gemini-3",
            "future_field_1": "should be ignored",
            "future_field_2": {"nested": "data"},
        }
        event = parser.parse(data)

        assert isinstance(event, LifecycleEvent)
        assert event.session_id == "abc123"
        # 原始数据仍然保留
        assert "future_field_1" in event.raw

    def test_extra_fields_ignored_codex(self):
        """Codex 事件中的额外字段应被忽略。"""
        parser = CodexParser()
        data = {
            "type": "thread.started",
            "thread_id": "123",
            "new_feature_flag": True,
            "experimental_data": [1, 2, 3],
        }
        event = parser.parse(data)

        assert isinstance(event, LifecycleEvent)
        assert event.session_id == "123"


class TestClaudeParser:
    """测试 Claude 解析器。"""

    def test_parse_init(self):
        """解析 system/init 事件。"""
        parser = ClaudeParser()
        data = {
            "type": "system",
            "subtype": "init",
            "session_id": "16cdb7ae-cabd-47ad-ad30-4efd2ce48b01",
            "model": "claude-opus-4-5-20251101",
            "cwd": "/path/to/project",
            "tools": ["Bash", "Read", "Write"],
            "mcp_servers": [
                {"name": "tavily", "status": "connected"},
                {"name": "codex", "status": "failed"},
            ],
            "claude_code_version": "2.0.69",
        }
        events = parser.parse(data)

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, LifecycleEvent)
        assert event.lifecycle_type == "session_start"
        assert event.session_id == "16cdb7ae-cabd-47ad-ad30-4efd2ce48b01"
        assert event.model == "claude-opus-4-5-20251101"
        assert event.source == CLISource.CLAUDE
        assert event.stats["tools_count"] == 3
        assert "tavily" in event.stats["mcp_servers"]

    def test_parse_thinking(self):
        """解析 assistant 消息中的 thinking。"""
        parser = ClaudeParser()
        data = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "The user wants me to introduce myself briefly.",
                    }
                ]
            },
            "session_id": "abc123",
        }
        events = parser.parse(data)

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, MessageEvent)
        assert event.content_type == ContentType.REASONING
        assert event.role == "assistant"
        assert "introduce myself" in event.text

    def test_parse_text_message(self):
        """解析 assistant 消息中的 text。"""
        parser = ClaudeParser()
        data = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Hello! I'm Claude, your AI assistant."}
                ]
            },
            "session_id": "abc123",
        }
        events = parser.parse(data)

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, MessageEvent)
        assert event.content_type == ContentType.TEXT
        assert event.role == "assistant"
        assert "Claude" in event.text

    def test_parse_tool_use(self):
        """解析 assistant 消息中的 tool_use。"""
        parser = ClaudeParser()
        data = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "Bash",
                        "input": {"command": "ls -la"},
                    }
                ]
            },
            "session_id": "abc123",
        }
        events = parser.parse(data)

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, OperationEvent)
        assert event.operation_type == OperationType.COMMAND
        assert event.name == "Bash"
        assert event.operation_id == "toolu_123"
        assert event.status == Status.RUNNING
        assert "ls -la" in event.input

    def test_parse_tool_result(self):
        """解析 user 消息中的 tool_result。"""
        parser = ClaudeParser()
        # 先解析 tool_use 以缓存工具名
        parser.parse({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "toolu_123", "name": "Bash", "input": {}}
                ]
            },
        })

        data = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_123",
                        "content": "total 16\ndrwxr-xr-x  3 user  staff  96",
                    }
                ]
            },
            "session_id": "abc123",
        }
        events = parser.parse(data)

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, OperationEvent)
        assert event.name == "Bash"  # 从缓存获取
        assert event.status == Status.SUCCESS
        assert "drwxr-xr-x" in event.output

    def test_parse_result(self):
        """解析 result 事件。"""
        parser = ClaudeParser()
        data = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 9832,
            "num_turns": 1,
            "total_cost_usd": 0.30612,
            "session_id": "abc123",
            "usage": {
                "input_tokens": 9,
                "output_tokens": 218,
                "cache_creation_input_tokens": 45732,
            },
        }
        events = parser.parse(data)

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, LifecycleEvent)
        assert event.lifecycle_type == "session_end"
        assert event.status == Status.SUCCESS
        assert event.stats["duration_ms"] == 9832
        assert event.stats["total_cost_usd"] == 0.30612

    def test_parse_multiple_content_blocks(self):
        """解析包含多个内容块的消息（thinking + tool_use）。"""
        parser = ClaudeParser()
        data = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "I need to list the files."},
                    {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}},
                ]
            },
        }
        events = parser.parse(data)

        # 应该产生 2 个事件
        assert len(events) == 2
        assert isinstance(events[0], MessageEvent)
        assert events[0].content_type == ContentType.REASONING
        assert isinstance(events[1], OperationEvent)
        assert events[1].name == "Bash"

    def test_parse_sample_file(self, claude_simple_greeting):
        """使用真实样本文件测试。"""
        parser = ClaudeParser()
        raw_events = claude_simple_greeting.get("events", [])

        all_parsed = []
        for raw in raw_events:
            all_parsed.extend(parser.parse(raw))

        # 验证第一个是 session_start
        lifecycle_events = [e for e in all_parsed if isinstance(e, LifecycleEvent)]
        assert len(lifecycle_events) >= 2
        assert lifecycle_events[0].lifecycle_type == "session_start"
        assert lifecycle_events[-1].lifecycle_type == "session_end"

        # 验证有消息事件
        message_events = [e for e in all_parsed if isinstance(e, MessageEvent)]
        assert len(message_events) >= 1

    def test_parse_tool_sample_file(self, claude_list_files):
        """使用包含工具调用的样本文件测试。"""
        parser = ClaudeParser()
        raw_events = claude_list_files.get("events", [])

        all_parsed = []
        for raw in raw_events:
            all_parsed.extend(parser.parse(raw))

        # 验证有操作事件（工具调用）
        operation_events = [e for e in all_parsed if isinstance(e, OperationEvent)]
        assert len(operation_events) >= 1

        # 应该有 Bash 调用
        bash_events = [e for e in operation_events if e.name == "Bash"]
        assert len(bash_events) >= 1


class TestClaudeConvenienceFunctions:
    """测试 Claude 相关的便捷函数。"""

    def test_parse_event_auto_detect_claude(self):
        """parse_event 自动检测 Claude。"""
        data = {
            "type": "system",
            "subtype": "init",
            "session_id": "abc",
            "claude_code_version": "2.0.0",
        }
        event = parse_event(data)

        assert event.source == CLISource.CLAUDE
        assert isinstance(event, LifecycleEvent)

    def test_parse_events_multiple(self):
        """parse_events 返回多个事件。"""
        data = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "Let me think..."},
                    {"type": "text", "text": "Here is my answer."},
                ]
            },
            "session_id": "abc",
        }
        events = parse_events(data)

        assert len(events) == 2
        assert isinstance(events[0], MessageEvent)
        assert isinstance(events[1], MessageEvent)

    def test_create_parser_claude(self):
        """create_parser 创建 Claude 解析器。"""
        parser = create_parser("claude")
        assert isinstance(parser, ClaudeParser)

        parser2 = create_parser(CLISource.CLAUDE)
        assert isinstance(parser2, ClaudeParser)
