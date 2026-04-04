"""Pipeline completa: prompt > RAG > agent > sandbox > SSE"""
import asyncio
from clow.sdk import Clow
from clow.rag import get_index
from clow.docker_sandbox import run_python_sandboxed, is_available as docker_ok
from clow.sse_stream import sse_stream
from clow.agent import Agent

print("=" * 60)
print("PIPELINE COMPLETA: prompt > RAG > agent > sandbox > SSE")
print("=" * 60)

# 1. RAG
print("\n[1/5] RAG")
idx = get_index("/root/clow")
ctx = idx.get_context("como o agent processa mensagens", max_chars=4000)
print(f"  Contexto: {len(ctx)} chars")

# 2. Agent + RAG
print("\n[2/5] Agent + RAG")
clow = Clow(project="/root/clow")
r = clow.ask("explique em 2 frases como run_turn funciona")
print(f"  Resposta: {r.text[:200]}")
print(f"  Tempo: {r.elapsed:.1f}s")

# 3. Sandbox
print("\n[3/5] Docker Sandbox")
print(f"  Disponivel: {docker_ok()}")
if docker_ok():
    sr = run_python_sandboxed("print('SANDBOX_OK')")
    print(f"  Output: {sr['stdout'].strip()}")

# 4. SSE
print("\n[4/5] SSE Stream")
async def test_sse():
    a = Agent(cwd="/root/clow", auto_approve=True)
    events = []
    async for ev in sse_stream(a, "diga: pipeline ok"):
        events.append(ev.strip())
        if "[DONE]" in ev:
            break
    return events

events = asyncio.run(test_sse())
types = []
for e in events:
    if '"type"' in e:
        try:
            types.append(e.split('"type": "')[1].split('"')[0])
        except IndexError:
            pass
print(f"  Events: {len(events)}, Types: {types}")

# 5. Resultado
print("\n[5/5] Validacao")
checks = {
    "RAG context": len(ctx) > 100,
    "Agent response": len(r.text) > 20,
    "Docker sandbox": docker_ok(),
    "SSE stream": "text_delta" in types and "turn_complete" in types,
}
for k, v in checks.items():
    print(f"  {'OK' if v else 'FAIL'} {k}")

print(f"\nPIPELINE: {'COMPLETA' if all(checks.values()) else 'INCOMPLETA'}")
