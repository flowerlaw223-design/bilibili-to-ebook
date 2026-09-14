# -*- coding: utf-8 -*-
"""界面外壳判据：既要拦住菜单栏/书签栏，又不能误伤讲技术的正常幻灯片。

这两个方向都踩过坑：
  - 用泛词（工具/设计/格式）判 → PPT 整本被判成菜单栏（49 张 -> 2 张）
  - 只用 Office 专属词     → Word 菜单栏漏网（"文件 开始 插入 引用 邮件 视图"）
"""
import pytest

from bbook import align as A

UI_SAMPLES = [
    "文件 开始 OPULIS 插入 引用 邮件 视图 PDF工具箱 助Acrobat",
    "标卖 百度 新波网 58网城 唯品会 京东商城 小红书 阿理1688平",
    "口 www.bilibil.com OVPN",
    "另存为 兼容性模式 已保存到本机 工具箱",
]

CONTENT_SAMPLES = [
    "GEN1 历史拐点 2023年6月13日 function calling 发布 模型不再仅生成给人看的自然语言",
    "结构化编排 把模型的思考放到一个可控的流程里面去 可靠性不再寄希望于模型一次性生成完美答案",
    "工具调用 的觉醒 如果说第零代 的 AI 只能够生成文本 那么第一代 的核心变化就是模型开始可以生成机器可读的结构化指令",
    "Al Agent 面试经验分享 至2026夏",
    "方向赛道 ·端云协同Agent ·Code Agent ·纯软件AI智能体",
]


@pytest.mark.parametrize("t", UI_SAMPLES)
def test_ui_chrome_is_detected(t):
    assert A.looks_like_ui_chrome(t) is True


@pytest.mark.parametrize("t", CONTENT_SAMPLES)
def test_real_content_is_not_flagged(t):
    assert A.looks_like_ui_chrome(t) is False


def test_empty_alternative_bug():
    """回归：正则里出现过 ||（空分支），会匹配任意位置导致整本误判。"""
    for rx in (A.UI_WORDS, A.MENU_WORDS, A.BRANDS, A.URLISH):
        assert "||" not in rx.pattern
