"""Clow SDK — clean Python API for programmatic usage.

Usage:
    from clow.sdk import Clow

    clow = Clow()
    result = clow.ask("crie um servidor Flask")
    print(result.text)

    # Streaming
    for chunk in clow.stream("refatore este codigo"):
        print(chunk, end="")

    # With RAG context
    clow = Clow(project="/path/to/project")
    result = clow.ask("como funciona o auth?")
"""
import os
import time
import logging
import threading
from dataclasses import dataclass, field
from typing import Generator

logger = logging.getLogger(__name__)


@dataclass
class ClowResponse:
    text: str
    tools_used: list[dict] = field(default_factory=list)
    elapsed: float = 0.0
    model: str = ""

    def __str__(self):
        return self.text

    def __bool__(self):
        return bool(self.text)


class Clow:
    def __init__(self, model: str = "", project: str = "", auto_approve: bool = True):
        self.project = project or os.getcwd()
        self.auto_approve = auto_approve
        from . import config
        self.model = model or config.CLOW_MODEL
        self._agent = None

    def _get_agent(self):
        if self._agent is None:
            from .agent import Agent
            self._agent = Agent(cwd=self.project, model=self.model, auto_approve=self.auto_approve)
        return self._agent

    def _rag_context(self, query: str) -> str:
        try:
            from .rag import get_context_for_prompt
            return get_context_for_prompt(query, root=self.project)
        except Exception:
            return ""

    def ask(self, prompt: str, use_rag: bool = True) -> ClowResponse:
        start = time.time()
        agent = self._get_agent()
        full = prompt
        if use_rag:
            ctx = self._rag_context(prompt)
            if ctx:
                full = f"{ctx}\n\n---\n\n{prompt}"
        tools = []
        agent.on_tool_call = lambda n, a: tools.append({"name": n, "args": a})
        result = agent.run_turn(full)
        return ClowResponse(text=result, tools_used=tools, elapsed=time.time() - start, model=self.model)

    def stream(self, prompt: str, use_rag: bool = True) -> Generator[str, None, None]:
        agent = self._get_agent()
        full = prompt
        if use_rag:
            ctx = self._rag_context(prompt)
            if ctx:
                full = f"{ctx}\n\n---\n\n{prompt}"
        chunks = []
        done = threading.Event()
        agent.on_text_delta = lambda d: chunks.append(d)
        agent.on_text_done = lambda t: done.set()

        def _run():
            try:
                agent.run_turn(full)
            finally:
                done.set()

        t = threading.Thread(target=_run)
        t.start()
        idx = 0
        while not done.is_set() or idx < len(chunks):
            while idx < len(chunks):
                yield chunks[idx]
                idx += 1
            if not done.is_set():
                time.sleep(0.02)

    def index_project(self) -> dict:
        from .rag import get_index
        return get_index(self.project).stats()

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        from .rag import search_codebase
        return search_codebase(query, root=self.project, top_k=top_k)

    def install_skill(self, name: str) -> dict:
        from .marketplace import install_skill
        return install_skill(name)

    def list_skills(self) -> list:
        from .marketplace import list_installed
        return list_installed()
