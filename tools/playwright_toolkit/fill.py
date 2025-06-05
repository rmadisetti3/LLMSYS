from __future__ import annotations
from typing import Optional, Type
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_community.tools.playwright.base import BaseBrowserTool
from langchain_community.tools.playwright.utils import (
    aget_current_page,
    get_current_page,
)


class FillToolInput(BaseModel):
    selector: str = Field(..., description="CSS selector for the element to fill")
    value: str = Field(None, description="text to be filled in element")


class FillTool(BaseBrowserTool):
    name: str = "fill_element"
    description: str = "Fill on an element with the given CSS selector"
    args_schema: Type[BaseModel] = FillToolInput
    visible_only: bool = False
    playwright_strict: bool = True
    playwright_timeout: float = 1_000

    def _selector_effective(self, selector: str) -> str:
        if not self.visible_only:
            return selector
        return f"{selector} >> visible=1"
    def _value_effective(self, value: str) -> str:
        if not self.visible_only:
            return value
        return f"{value}"

    def _run(
        self,
        selector: str,
        value: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        if self.sync_browser is None:
            raise ValueError(f"Synchronous browser not provided to {self.name}")
        page = get_current_page(self.sync_browser)
        selector_effective = self._selector_effective(selector=selector)
        value_effective = self._value_effective(value=value)
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        try:
            page.fill(
                selector_effective,
                value_effective,
                strict=self.playwright_strict,
                timeout=self.playwright_timeout,
            )
        except Exception as e:
            return f"Unable to Fill on element '{selector}' error: {e}"
        return f"Filled element '{selector}' with Value: {value}"

    async def _arun(
        self,
        selector: str,
        value:str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        if self.async_browser is None:
            raise ValueError(f"Asynchronous browser not provided to {self.name}")
        page = await aget_current_page(self.async_browser)
        selector_effective = self._selector_effective(selector=selector)
        value_effective = self._value_effective(value=value)
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        try:
            await page.fill(
                selector_effective,
                value_effective,
                strict=self.playwright_strict,
                timeout=self.playwright_timeout,
            )
        except PlaywrightTimeoutError:
            return f"Unable to Fill on element '{selector}'"
        return f"Filled element '{selector}' with Value: {value}"
        