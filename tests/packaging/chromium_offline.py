"""Run using bundled Python -I, only inside PID/mount/network isolation.

Requires an empty HOME and ODIN_DESKTOP_BUNDLE_ROOT pointing at the read-only
candidate runtime. Does not rely on pytest or a source checkout.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from src.tools.browser import BrowserManager


async def main():
    assert os.getuid() != 0
    assert not os.environ.get("DISPLAY")
    assert not os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    assert not list(Path.home().iterdir()), "first use must have an empty HOME"
    root = Path(os.environ["ODIN_DESKTOP_BUNDLE_ROOT"])
    assert sys.executable.startswith(str(root))
    manager = BrowserManager()
    await manager._ensure_connected()
    try:
        context, page = await manager._create_page()
        await page.goto("data:text/html,<title>Python D14 offline</title><h1>Bundled Chromium</h1>")
        assert await page.title() == "Python D14 offline"
        image = await page.screenshot()
        assert image[1:4] == b"PNG"
        children = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                command = (
                    (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
                )
                if "chrome-headless-shell" not in command:
                    continue
                assert " --no-sandbox " not in command
                assert " --disable-setuid-sandbox " not in command
                status = (entry / "status").read_text()
                if " --type=renderer " in command:
                    assert "Seccomp:\t2" in status
                    assert "NoNewPrivs:\t1" in status
                    children.append(int(entry.name))
            except FileNotFoundError:
                continue
        assert children, "renderer sandbox must be observed"
        print(json.dumps({"version": manager._browser.version, "python": sys.version,
                          "executable": manager._bundled_executable,
                          "title": await page.title(), "screenshot_bytes": len(image),
                          "sandboxed_renderer_pids": children}, indent=2))
        await context.close()
    finally:
        await manager._browser.close()
        await manager._playwright.stop()


asyncio.run(main())
