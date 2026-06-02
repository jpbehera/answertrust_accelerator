"""Render answertrust_dashboard_mockup.html to PNG via headless chromium."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

HERE = Path(__file__).parent
HTML = HERE / "answertrust_dashboard_mockup.html"
OUT = HERE / "images" / "answertrust_dashboard_mockup.png"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": 1340, "height": 820},
            device_scale_factor=2,
        )
        page = await ctx.new_page()
        await page.goto(HTML.as_uri())
        await page.add_style_tag(content="body{background:#fff !important;margin:0;} .frame{margin:0 !important; box-shadow:none !important;}")
        el = await page.query_selector(".frame")
        OUT.parent.mkdir(exist_ok=True)
        await el.screenshot(path=str(OUT), omit_background=False)
        await browser.close()
        print(f"wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
