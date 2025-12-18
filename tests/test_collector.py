"""ResultCollector 单元测试。

测试结果收集器的核心功能：
- 事件处理和消息收集
- session_id 提取
- debug 信息统计
- 错误分类
"""

import pytest
from dataclasses import dataclass
from enum import Enum
from typing import Any

from cli_agent_mcp.shared.invokers.collector import (
    ResultCollector,
    ErrorCategory,
    CollectedResult,
)
from cli_agent_mcp.shared.invokers.types import DebugInfo


# Mock UnifiedEvent for testing
class MockCategory(Enum):
    MESSAGE = "message"
    OPERATION = "operation"
    SYSTEM = "system"


class MockOperationType(Enum):
    TOOL_CALL = "tool_call"
    FUNCTION_CALL = "function_call"
    COMMAND = "command"


class MockContentType(Enum):
    TEXT = "text"
    REASONING = "reasoning"


@dataclass
class MockEvent:
    """Mock event for testing."""
    category: MockCategory
    raw: dict[str, Any]
    role: str = ""
    text: str = ""
    is_delta: bool = False
    session_id: str = ""
    content_type: MockContentType = MockContentType.TEXT
    operation_type: MockOperationType | None = None


class TestResultCollectorBasic:
    """基本功能测试。"""

    def test_init(self):
        """初始化测试。"""
        collector = ResultCollector()
        result = collector.get_result()

        assert result.session_id == ""
        assert result.final_answer == ""
        assert result.thought_steps == []
        assert result.error_category == ErrorCategory.NONE
        assert result.success is True

    def test_process_single_message(self):
        """处理单条消息。"""
        collector = ResultCollector()

        event = MockEvent(
            category=MockCategory.MESSAGE,
            raw={"type": "message"},
            role="assistant",
            text="Hello, world!",
            is_delta=False,
        )
        collector.process_event(event)

        result = collector.get_result()
        assert result.final_answer == "Hello, world!"
        assert result.thought_steps == []
        assert result.debug_info.message_count == 1


class TestSessionIdExtraction:
    """session_id 提取测试。"""

    def test_extract_session_id(self):
        """提取 session_id。"""
        collector = ResultCollector()

        event = MockEvent(
            category=MockCategory.SYSTEM,
            raw={"type": "system"},
            session_id="test-session-123",
        )
        collector.process_event(event)

        assert collector.session_id == "test-session-123"

    def test_session_id_only_set_once(self):
        """session_id 只设置一次。"""
        collector = ResultCollector()

        event1 = MockEvent(
            category=MockCategory.SYSTEM,
            raw={},
            session_id="first-session",
        )
        event2 = MockEvent(
            category=MockCategory.SYSTEM,
            raw={},
            session_id="second-session",
        )

        collector.process_event(event1)
        collector.process_event(event2)

        assert collector.session_id == "first-session"


class TestMessageCollection:
    """消息收集测试。"""

    def test_delta_message_accumulation(self):
        """Delta 消息累积。"""
        collector = ResultCollector()

        events = [
            MockEvent(
                category=MockCategory.MESSAGE,
                raw={},
                role="assistant",
                text="Hello, ",
                is_delta=True,
            ),
            MockEvent(
                category=MockCategory.MESSAGE,
                raw={},
                role="assistant",
                text="world!",
                is_delta=True,
            ),
        ]

        for event in events:
            collector.process_event(event)

        result = collector.get_result()
        assert result.final_answer == "Hello, world!"

    def test_complete_message_replaces(self):
        """完整消息替换之前的。"""
        collector = ResultCollector()

        events = [
            MockEvent(
                category=MockCategory.MESSAGE,
                raw={},
                role="assistant",
                text="First answer",
                is_delta=False,
            ),
            MockEvent(
                category=MockCategory.MESSAGE,
                raw={},
                role="assistant",
                text="Second answer",
                is_delta=False,
            ),
        ]

        for event in events:
            collector.process_event(event)

        result = collector.get_result()
        assert result.final_answer == "Second answer"
        assert result.thought_steps == ["First answer"]

    def test_reasoning_excluded(self):
        """reasoning 类型排除。"""
        collector = ResultCollector()

        events = [
            MockEvent(
                category=MockCategory.MESSAGE,
                raw={},
                role="assistant",
                text="Thinking...",
                is_delta=False,
                content_type=MockContentType.REASONING,
            ),
            MockEvent(
                category=MockCategory.MESSAGE,
                raw={},
                role="assistant",
                text="Final answer",
                is_delta=False,
                content_type=MockContentType.TEXT,
            ),
        ]

        for event in events:
            collector.process_event(event)

        result = collector.get_result()
        assert result.final_answer == "Final answer"
        assert "Thinking" not in result.final_answer

    def test_user_message_ignored(self):
        """用户消息忽略。"""
        collector = ResultCollector()

        event = MockEvent(
            category=MockCategory.MESSAGE,
            raw={},
            role="user",
            text="User input",
            is_delta=False,
        )
        collector.process_event(event)

        result = collector.get_result()
        assert result.final_answer == ""


class TestDebugInfoExtraction:
    """Debug 信息提取测试。"""

    def test_model_extraction(self):
        """提取模型名称。"""
        collector = ResultCollector()

        event = MockEvent(
            category=MockCategory.MESSAGE,
            raw={"model": "gpt-4"},
        )
        collector.process_event(event)

        assert collector.debug_info.model == "gpt-4"

    def test_model_from_metadata(self):
        """从 metadata 提取模型名称。"""
        collector = ResultCollector()

        event = MockEvent(
            category=MockCategory.MESSAGE,
            raw={"metadata": {"model": "claude-3"}},
        )
        collector.process_event(event)

        assert collector.debug_info.model == "claude-3"

    def test_token_stats_extraction(self):
        """提取 token 统计。"""
        collector = ResultCollector()

        event = MockEvent(
            category=MockCategory.MESSAGE,
            raw={
                "stats": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                }
            },
        )
        collector.process_event(event)

        assert collector.debug_info.input_tokens == 100
        assert collector.debug_info.output_tokens == 50

    def test_gemini_token_stats(self):
        """Gemini 格式 token 统计。"""
        collector = ResultCollector()

        event = MockEvent(
            category=MockCategory.MESSAGE,
            raw={
                "stats": {
                    "total_input_tokens": 200,
                    "total_output_tokens": 100,
                }
            },
        )
        collector.process_event(event)

        assert collector.debug_info.input_tokens == 200
        assert collector.debug_info.output_tokens == 100

    def test_tool_call_count(self):
        """工具调用计数。"""
        collector = ResultCollector()

        events = [
            MockEvent(
                category=MockCategory.OPERATION,
                raw={},
                operation_type=MockOperationType.TOOL_CALL,
            ),
            MockEvent(
                category=MockCategory.OPERATION,
                raw={},
                operation_type=MockOperationType.FUNCTION_CALL,
            ),
            MockEvent(
                category=MockCategory.OPERATION,
                raw={},
                operation_type=MockOperationType.COMMAND,
            ),
        ]

        for event in events:
            collector.process_event(event)

        assert collector.debug_info.tool_call_count == 3


class TestErrorHandling:
    """错误处理测试。"""

    def test_set_exit_error(self):
        """设置退出错误。"""
        collector = ResultCollector()
        collector.set_exit_error(1, "Error output")

        result = collector.get_result()
        assert result.error_category == ErrorCategory.EXIT_ERROR
        assert result.exit_code == 1
        assert "code 1" in result.error_message
        assert result.success is False

    def test_set_cancelled(self):
        """设置取消状态。"""
        collector = ResultCollector()
        collector.set_cancelled()

        result = collector.get_result()
        assert result.error_category == ErrorCategory.CANCELLED
        assert result.cancelled is True
        assert result.success is False

    def test_set_validation_error(self):
        """设置验证错误。"""
        collector = ResultCollector()
        collector.set_validation_error("Invalid param")

        result = collector.get_result()
        assert result.error_category == ErrorCategory.VALIDATION_ERROR
        assert result.error_message == "Invalid param"

    def test_set_internal_error(self):
        """设置内部错误。"""
        collector = ResultCollector()
        collector.set_internal_error("Parse failed")

        result = collector.get_result()
        assert result.error_category == ErrorCategory.INTERNAL_ERROR
        assert result.error_message == "Parse failed"


class TestNonJsonLineProcessing:
    """非 JSON 行处理测试。"""

    def test_api_error_extraction(self):
        """提取 API 错误。"""
        collector = ResultCollector()

        line = "Attempt 1 failed with status 429. Rate limit ApiError: Too many requests"
        result = collector.process_non_json_line(line)

        assert result is not None
        category, msg = result
        assert category == ErrorCategory.API_ERROR
        assert "429" in msg

    def test_startup_log_ignored(self):
        """忽略启动日志。"""
        collector = ResultCollector()

        line = "[STARTUP] Loading model..."
        result = collector.process_non_json_line(line)

        assert result is None

    def test_regular_line_ignored(self):
        """忽略普通行。"""
        collector = ResultCollector()

        line = "Some random output"
        result = collector.process_non_json_line(line)

        assert result is None


class TestCollectedResult:
    """CollectedResult 测试。"""

    def test_success_property(self):
        """success 属性测试。"""
        result = CollectedResult()
        assert result.success is True

        result.error_category = ErrorCategory.EXIT_ERROR
        assert result.success is False

    def test_cancelled_property(self):
        """cancelled 属性测试。"""
        result = CollectedResult()
        assert result.cancelled is False

        result.error_category = ErrorCategory.CANCELLED
        assert result.cancelled is True

    def test_to_execution_result(self):
        """转换为 ExecutionResult。"""
        result = CollectedResult(
            session_id="test-123",
            final_answer="Answer",
            thought_steps=["Step 1"],
            debug_info=DebugInfo(model="test-model"),
        )

        exec_result = result.to_execution_result(
            cli_name="codex",
            task_note="Test task",
            start_time=100.0,
            end_time=110.0,
            verbose_output=True,
        )

        assert exec_result.success is True
        assert exec_result.session_id == "test-123"
        assert exec_result.agent_messages == "Answer"
        assert exec_result.thought_steps == ["Step 1"]
        assert exec_result.gui_metadata.task_note == "Test task"
        assert exec_result.debug_info.duration_sec == 10.0


class TestErrorCategory:
    """ErrorCategory 枚举测试。"""

    def test_all_categories(self):
        """所有错误分类。"""
        categories = [
            ErrorCategory.NONE,
            ErrorCategory.CANCELLED,
            ErrorCategory.EXIT_ERROR,
            ErrorCategory.API_ERROR,
            ErrorCategory.VALIDATION_ERROR,
            ErrorCategory.INTERNAL_ERROR,
        ]

        assert len(categories) == 6

    def test_category_values(self):
        """错误分类值。"""
        assert ErrorCategory.NONE.value == "none"
        assert ErrorCategory.CANCELLED.value == "cancelled"
        assert ErrorCategory.EXIT_ERROR.value == "exit_error"
