"""
截图脚本：给 submission/ 生成三张作业用截图
==================================================

用法（先确保 local_dev.py 已经起来）：
    .venv\\Scripts\\python.exe tests\\shot.py

产出：
    submission/01-local-running.png    本地服务首页（空态）
    submission/02-scenario1.png        场景一：信息完整
    submission/03-scenario2.png        场景二：连续追问

用本机已安装的 Chrome（channel="chrome"），不下载 Playwright 自带的浏览器。
本机有 http_proxy 环境变量，浏览器用 --no-proxy-server 直连 127.0.0.1。
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "submission"
URL = "http://127.0.0.1:8787"


def wait_idle(page, timeout: int = 90_000) -> None:
    """等本轮回答结束：输入框从 disabled 恢复可用，且不再有 text_delta 流入。"""
    page.wait_for_function(
        """() => {
            const ta = document.querySelector('textarea');
            return ta && !ta.disabled;
        }""",
        timeout=timeout,
    )
    page.wait_for_timeout(1200)  # 留点时间给动画/滚动落位
    page.mouse.move(4, 4)        # 鼠标移开，避免截图里留下预设问题的悬停高亮
    page.evaluate("() => { document.activeElement instanceof HTMLElement && document.activeElement.blur(); window.getSelection()?.removeAllRanges(); }")
    page.wait_for_timeout(350)   # 等按钮的 hover/focus 过渡色退干净再截


def main() -> int:
    OUT.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--no-proxy-server", "--force-device-scale-factor=2"],
        )
        ctx = browser.new_context(
            viewport={"width": 1600, "height": 1100},
            device_scale_factor=2,
            locale="zh-CN",
        )
        page = ctx.new_page()

        page.goto(URL, wait_until="networkidle", timeout=30_000)
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "01-local-running.png"))
        print("已保存 01-local-running.png")

        presets = page.locator("button", has_text="红莲南路")
        presets.first.click()
        wait_idle(page)
        page.screenshot(path=str(OUT / "02-scenario1.png"))
        print("已保存 02-scenario1.png")

        page.locator("button", has_text="不要求两个品牌").first.click()
        wait_idle(page)
        page.screenshot(path=str(OUT / "03-scenario2.png"))
        print("已保存 03-scenario2.png")

        # 顺便把回答正文导出成文本，便于人工核对内容
        bubbles = page.locator("[class*='bubble'], [class*='Bubble']")
        texts = [b.inner_text() for b in bubbles.all()][-4:]
        (OUT / "answers.txt").write_text("\n\n" + "\n\n---\n\n".join(texts), encoding="utf-8")
        print(f"回答正文已导出 answers.txt（{len(texts)} 段）")

        ctx.close()
        browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
