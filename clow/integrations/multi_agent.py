"""Multi-agent team orchestration via PraisonAI.

Create teams of AI agents that collaborate on complex tasks.
Install: pip install praisonaiagents
"""
import logging

logger = logging.getLogger(__name__)


def is_available() -> bool:
    try:
        from praisonaiagents import Agent
        return True
    except ImportError:
        return False


async def run_team(task: str, team_type: str = "research") -> str:
    if not is_available():
        return "PraisonAI nao instalado. Execute: pip install praisonaiagents"
    try:
        from praisonaiagents import Agent, Agents
        teams = {
            "research": [
                Agent(name="Researcher", instructions="Pesquise informacoes relevantes"),
                Agent(name="Analyst", instructions="Analise os dados e identifique insights"),
                Agent(name="Writer", instructions="Escreva um relatorio conciso"),
            ],
            "development": [
                Agent(name="Architect", instructions="Planeje a arquitetura"),
                Agent(name="Developer", instructions="Implemente o codigo"),
                Agent(name="Reviewer", instructions="Revise e sugira melhorias"),
            ],
            "marketing": [
                Agent(name="Strategist", instructions="Defina a estrategia de marketing"),
                Agent(name="Copywriter", instructions="Crie textos e copies"),
                Agent(name="Analyst", instructions="Analise metricas e otimize"),
            ],
        }
        agents = teams.get(team_type, teams["research"])
        team = Agents(agents=agents)
        result = await team.astart(task)
        return str(result)
    except Exception as e:
        return f"Erro no time de agentes: {str(e)}"


def list_teams() -> list:
    return ["research", "development", "marketing"]
