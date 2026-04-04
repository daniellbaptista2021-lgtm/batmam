"""Browser automation via browser-use library.

Allows Clow to navigate websites, fill forms, extract data, take screenshots.
Install: pip install browser-use langchain-anthropic
"""
import logging
import os

logger = logging.getLogger(__name__)


async def browse(task: str, url: str = "", headless: bool = True) -> str:
    """Execute a browser automation task."""
    try:
        from browser_use import Agent as BrowserAgent
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        return "browser-use nao instalado. Execute: pip install browser-use langchain-anthropic"
    llm = ChatAnthropic(model="claude-sonnet-4-20250514", api_key=os.getenv("ANTHROPIC_API_KEY", ""))
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
