"""Modulo Redis — gestao de keys e monitoramento."""
from __future__ import annotations


def _connect(creds: dict):
    import redis
    return redis.Redis(
        host=creds.get("host", "localhost"),
        port=int(creds.get("port", 6379)),
        password=creds.get("password") or None,
        decode_responses=True,
        socket_timeout=30,
    )


def get_key(creds: dict, key: str) -> str:
    r = _connect(creds)
    val = r.get(key)
    if val is None:
        return f"Key `{key}` nao encontrada."
    return f"**{key}** = `{str(val)[:500]}`"


def set_key(creds: dict, key: str, value: str, ttl: int = None) -> str:
    r = _connect(creds)
    r.set(key, value, ex=ttl)
    msg = f"✅ Key `{key}` salva."
    if ttl:
        msg += f" TTL: {ttl}s"
    return msg


def delete_key(creds: dict, key: str) -> str:
    r = _connect(creds)
    deleted = r.delete(key)
    return f"✅ {deleted} key(s) deletada(s)." if deleted else f"Key `{key}` nao encontrada."


def list_keys(creds: dict, pattern: str = "*") -> str:
    r = _connect(creds)
    keys = list(r.scan_iter(match=pattern, count=200))[:100]
    if not keys:
        return f"Nenhuma key encontrada para `{pattern}`."
    lines = [f"## Keys ({len(keys)} encontradas)\n"]
    for k in sorted(keys):
        t = r.type(k)
        lines.append(f"- `{k}` ({t})")
    return "\n".join(lines)


def memory_info(creds: dict) -> str:
    r = _connect(creds)
    info = r.info("memory")
    return (
        f"## Redis Memory\n\n"
        f"- Uso: {info.get('used_memory_human', '-')}\n"
        f"- Pico: {info.get('used_memory_peak_human', '-')}\n"
        f"- Keys: {r.dbsize()}\n"
        f"- Fragmentacao: {info.get('mem_fragmentation_ratio', '-')}"
    )
