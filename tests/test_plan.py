from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import plan  # noqa: E402


def test_real_document_maps_each_kind_of_day():
    """真实计划文档里，服务第 1/2/3 天与不在区间各对应一个小节。"""
    assert plan.today_plan(1)["title"] == "初识日"
    assert plan.today_plan(2)["title"] == "拆解跟读日"
    assert plan.today_plan(3)["title"] == "输出日"
    assert plan.today_plan(None)["title"] == "综合复盘日"


def test_real_document_steps_are_not_empty():
    for day in (1, 2, 3, None):
        section = plan.today_plan(day)
        assert section is not None, f"第 {day} 天应取到一个小节"
        assert section["steps"], f"第 {day} 天应至少有一条步骤"


def test_missing_file_degrades_quietly(tmp_path):
    missing = tmp_path / "nope.md"
    assert plan.load_sections(missing) == []
    assert plan.today_plan(1, path=missing) is None


def test_parses_document_and_ignores_other_sections(tmp_path):
    doc = tmp_path / "LEARNING_PLAN.md"
    doc.write_text(
        "# 计划\n\n"
        "## 3. 每天的学习安排\n\n"
        "### 周一，资源 A 初识日\n\n"
        "1. 第一步\n"
        "2. 第二步\n\n"
        "**目标**：这里不是步骤，应被忽略\n\n"
        "### 周四，资源 B 初识日\n\n"
        "同周一流程，换成资源 B。\n\n"
        "### 周日，综合复盘日\n\n"
        "1. 复盘一件事\n\n"
        "## 4. 之后的内容\n\n"
        "### 不该被读到\n\n"
        "1. 假的步骤\n",
        encoding="utf-8",
    )

    assert plan.today_plan(1, path=doc) == {"title": "初识日", "steps": ["第一步", "第二步"]}
    assert plan.today_plan(None, path=doc) == {"title": "综合复盘日", "steps": ["复盘一件事"]}

    # 第 3 天按「输出」找，这份文档里没有该小节
    assert plan.today_plan(3, path=doc) is None

    # 第 4 节的小节不该被读到，且没有步骤的小节要被丢掉
    titles = [section["title"] for section in plan.load_sections(doc)]
    assert titles == ["初识日", "综合复盘日"]
