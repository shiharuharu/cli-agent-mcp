"""请求编排与管理模块。

提供请求级别的隔离和管理，包括：
- RequestRegistry: 活动请求的登记和管理
- 请求级别的取消支持

这是信号隔离策略的核心组件之一。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional

__all__ = ["RequestRegistry", "RequestInfo"]

logger = logging.getLogger(__name__)


@dataclass
class RequestInfo:
    """活动请求的信息。

    Attributes:
        request_id: 唯一请求标识符
        cli_type: CLI 类型 (codex/gemini/claude)
        task: 关联的 asyncio Task
        created_at: 创建时间
        task_note: 可选的任务说明
    """

    request_id: str
    cli_type: str
    task: asyncio.Task
    created_at: datetime = field(default_factory=datetime.now)
    task_note: str = ""

    def __repr__(self) -> str:
        elapsed = (datetime.now() - self.created_at).total_seconds()
        status = "running" if not self.task.done() else "done"
        return (
            f"RequestInfo(id={self.request_id[:8]}..., "
            f"cli={self.cli_type}, "
            f"status={status}, "
            f"elapsed={elapsed:.1f}s)"
        )


class RequestRegistry:
    """活动请求的注册表。

    管理所有正在执行的请求，提供：
    - 请求登记和注销
    - 批量取消
    - 活动状态查询

    线程安全：所有操作都是同步的，由调用方保证在同一个事件循环中调用。

    Example:
        ```python
        registry = RequestRegistry()

        # 登记请求
        task = asyncio.create_task(some_coroutine())
        registry.register("req-1", "codex", task)

        # 检查状态
        if registry.has_active_requests():
            print(f"Active: {registry.active_count}")

        # 取消所有请求
        cancelled = registry.cancel_all()
        print(f"Cancelled {cancelled} requests")

        # 注销（通常在 task 完成后）
        registry.unregister("req-1")
        ```
    """

    def __init__(self) -> None:
        """初始化请求注册表。"""
        self._requests: Dict[str, RequestInfo] = {}
        self._on_empty_callbacks: list[Callable[[], None]] = []

    @staticmethod
    def generate_request_id() -> str:
        """生成唯一的请求 ID。

        Returns:
            UUID4 格式的字符串
        """
        return str(uuid.uuid4())

    def register(
        self,
        request_id: str,
        cli_type: str,
        task: asyncio.Task,
        task_note: str = "",
    ) -> None:
        """登记新请求。

        Args:
            request_id: 唯一请求标识符
            cli_type: CLI 类型 (codex/gemini/claude)
            task: 关联的 asyncio Task
            task_note: 可选的任务说明

        Raises:
            ValueError: 如果 request_id 已存在
        """
        if request_id in self._requests:
            raise ValueError(f"Request {request_id} already registered")

        info = RequestInfo(
            request_id=request_id,
            cli_type=cli_type,
            task=task,
            task_note=task_note,
        )
        self._requests[request_id] = info
        logger.debug(f"Registered request: {info}")

    def unregister(self, request_id: str) -> bool:
        """注销请求。

        Args:
            request_id: 请求标识符

        Returns:
            是否成功注销（请求存在则返回 True）
        """
        if request_id in self._requests:
            info = self._requests.pop(request_id)
            logger.debug(f"Unregistered request: {info}")

            # 如果注册表变空，触发回调
            if not self._requests and self._on_empty_callbacks:
                for callback in self._on_empty_callbacks:
                    try:
                        callback()
                    except Exception as e:
                        logger.warning(f"Error in on_empty callback: {e}")

            return True
        return False

    def get(self, request_id: str) -> Optional[RequestInfo]:
        """获取请求信息。

        Args:
            request_id: 请求标识符

        Returns:
            请求信息，如果不存在则返回 None
        """
        return self._requests.get(request_id)

    def cancel(self, request_id: str) -> bool:
        """取消指定请求。

        Args:
            request_id: 请求标识符

        Returns:
            是否成功发起取消（请求存在且未完成则返回 True）
        """
        info = self._requests.get(request_id)
        if info and not info.task.done():
            info.task.cancel()
            logger.info(f"Cancelled request: {info}")
            return True
        return False

    def cancel_all(self) -> int:
        """取消所有活动请求。

        Returns:
            成功发起取消的请求数量
        """
        cancelled = 0
        for info in list(self._requests.values()):
            if not info.task.done():
                info.task.cancel()
                logger.info(f"Cancelled request: {info}")
                cancelled += 1

        if cancelled > 0:
            logger.info(f"Cancelled {cancelled} active request(s)")

        return cancelled

    def has_active_requests(self) -> bool:
        """检查是否有活动请求。

        Returns:
            是否存在未完成的请求
        """
        return any(not info.task.done() for info in self._requests.values())

    @property
    def active_count(self) -> int:
        """获取活动请求数量。

        Returns:
            未完成的请求数量
        """
        return sum(1 for info in self._requests.values() if not info.task.done())

    @property
    def total_count(self) -> int:
        """获取总请求数量（包括已完成但未注销的）。

        Returns:
            注册表中的请求总数
        """
        return len(self._requests)

    def list_active(self) -> list[RequestInfo]:
        """列出所有活动请求。

        Returns:
            活动请求列表（按创建时间排序）
        """
        active = [info for info in self._requests.values() if not info.task.done()]
        return sorted(active, key=lambda x: x.created_at)

    def add_on_empty_callback(self, callback: Callable[[], None]) -> None:
        """添加注册表变空时的回调。

        当所有请求都被注销后，会调用这些回调。
        用于 SignalManager 判断是否可以退出。

        Args:
            callback: 无参数的回调函数
        """
        self._on_empty_callbacks.append(callback)

    def remove_on_empty_callback(self, callback: Callable[[], None]) -> None:
        """移除注册表变空时的回调。

        Args:
            callback: 要移除的回调函数
        """
        if callback in self._on_empty_callbacks:
            self._on_empty_callbacks.remove(callback)

    def cleanup_done(self) -> int:
        """清理已完成但未注销的请求。

        Returns:
            清理的请求数量
        """
        done_ids = [
            request_id
            for request_id, info in self._requests.items()
            if info.task.done()
        ]

        for request_id in done_ids:
            self.unregister(request_id)

        if done_ids:
            logger.debug(f"Cleaned up {len(done_ids)} done request(s)")

        return len(done_ids)

    def __len__(self) -> int:
        """返回注册表中的请求数量。"""
        return len(self._requests)

    def __contains__(self, request_id: str) -> bool:
        """检查请求是否在注册表中。"""
        return request_id in self._requests
