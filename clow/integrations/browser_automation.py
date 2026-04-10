"""Browser automation via browser-use library.

Allows Clow to navigate websites, fill forms, extract data, take screenshots.
Install: pip install browser-use langchain-openai
"""
import logging
import os

logger = logging.getLogger(__name__)


async def browse(task: str, url: str = "", headless: bool = True) -> str:
    """Execute a browser automation task."""
    try:
        from browser_use import Agent as BrowserAgent
        from langchain_openai import ChatOpenAI
    except ImportError:
        return "browser-use nao instalado. Execute: pip install browser-use langchain-openai"
    from .. import config
    base = config.DEEPSEEK_BASE_URL.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    llm = ChatOpenAI(model=config.CLOW_MODEL, api_key=config.DEEPSEEK_API_KEY, base_url=base)
    full_task = f"Acesse {url} e {task}" if url else task
    agent = BrowserAgent(task=full_task, llm=llm, browser_config={"headless": headless})
    result = await agent.run()
    return str(result)


def is_available() -> bool:
    try:
        import browser_use
        return True
    except ImportError:
        return False
