"""Pytest 配置和 fixtures。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 添加 shared 目录到 Python 路径（开发时）
SHARED_DIR = PROJECT_ROOT / "shared"
if SHARED_DIR.exists() and str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

# 添加 src 目录到 Python 路径
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# 样本数据目录
SAMPLES_DIR = PROJECT_ROOT / "dev-docs" / "samples"


@pytest.fixture
def project_root() -> Path:
    """项目根目录。"""
    return PROJECT_ROOT


@pytest.fixture
def samples_dir() -> Path:
    """样本数据目录。"""
    return SAMPLES_DIR


@pytest.fixture
def codex_simple_greeting() -> dict:
    """Codex 简单问候样本。"""
    sample_file = SAMPLES_DIR / "codex" / "simple_greeting_20251216_134103.json"
    if sample_file.exists():
        with open(sample_file, encoding="utf-8") as f:
            return json.load(f)
    pytest.skip("Sample file not found")


@pytest.fixture
def codex_code_analysis() -> dict:
    """Codex 代码分析样本。"""
    sample_file = SAMPLES_DIR / "codex" / "code_analysis_20251216_134157.json"
    if sample_file.exists():
        with open(sample_file, encoding="utf-8") as f:
            return json.load(f)
    pytest.skip("Sample file not found")


@pytest.fixture
def gemini_simple_greeting() -> dict:
    """Gemini 简单问候样本。"""
    sample_file = SAMPLES_DIR / "gemini" / "simple_greeting_20251216_134103.json"
    if sample_file.exists():
        with open(sample_file, encoding="utf-8") as f:
            return json.load(f)
    pytest.skip("Sample file not found")


@pytest.fixture
def gemini_code_analysis() -> dict:
    """Gemini 代码分析样本。"""
    sample_file = SAMPLES_DIR / "gemini" / "code_analysis_20251216_134157.json"
    if sample_file.exists():
        with open(sample_file, encoding="utf-8") as f:
            return json.load(f)
    pytest.skip("Sample file not found")


@pytest.fixture
def claude_simple_greeting() -> dict:
    """Claude 简单问候样本。"""
    sample_file = SAMPLES_DIR / "claude" / "simple_greeting_20251216_141901.json"
    if sample_file.exists():
        with open(sample_file, encoding="utf-8") as f:
            return json.load(f)
    pytest.skip("Sample file not found")


@pytest.fixture
def claude_list_files() -> dict:
    """Claude 列出文件样本（包含工具调用）。"""
    # 查找最新的 list_files 样本
    claude_dir = SAMPLES_DIR / "claude"
    if claude_dir.exists():
        files = list(claude_dir.glob("list_files_*.json"))
        if files:
            with open(sorted(files)[-1], encoding="utf-8") as f:
                return json.load(f)
    pytest.skip("Sample file not found")
