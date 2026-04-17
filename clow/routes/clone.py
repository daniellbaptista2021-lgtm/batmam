"""Clone API Routes — POST /api/v1/clone + GET /api/v1/clone/jobs/{id}.

Jobs rodam em background thread (ThreadPoolExecutor). State em memoria — pra MVP.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR

logger = logging.getLogger(__name__)

# Estado global de jobs (em memoria — perde no restart)
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="clone-")


def _set_job(job_id: str, **patch: Any) -> None:
    with _JOBS_LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(patch)


def _new_job(user_id: int, url: str, output_dir: str, skip_qa: bool, skip_build: bool) -> str:
    job_id = uuid.uuid4().hex[:16]
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "user_id": user_id,
            "url": url,
            "output_dir": output_dir,
            "skip_qa": skip_qa,
            "skip_build": skip_build,
            "status": "queued",
            "progress": [],
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
        }
    return job_id


def _run_job(job_id: str) -> None:
    from ..skills.website_cloner import clone_site

    with _JOBS_LOCK:
        job = dict(_JOBS.get(job_id, {}))
    if not job:
        return

    _set_job(job_id, status="running", started_at=time.time())

    def progress(phase: str, status: str, info: dict):
        with _JOBS_LOCK:
            if job_id in _JOBS:
                _JOBS[job_id]["progress"].append({
                    "phase": phase,
                    "status": status,
                    "info": info,
                    "ts": time.time(),
                })

    try:
        result = clone_site(
            url=job["url"],
            output_dir=job["output_dir"],
            skip_qa=job["skip_qa"],
            skip_build=job["skip_build"],
            progress_cb=progress,
        )
        _set_job(
            job_id,
            status=result.get("status", "ok"),
            result=result,
            finished_at=time.time(),
        )
    except Exception as e:
        logger.exception("clone job %s crashed", job_id)
        _set_job(job_id, status="error", error=str(e), finished_at=time.time())


def register_clone_routes(app) -> None:
    from .auth import _get_user_session

    @app.post("/api/v1/clone", tags=["clone"])
    async def create_clone_job(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        try:
            data = await request.json()
        except Exception:
            return _JR({"error": "JSON invalido"}, status_code=400)

        url = (data.get("url") or "").strip()
        if not url or not url.startswith(("http://", "https://")):
            return _JR({"error": "URL invalida (precisa http:// ou https://)"}, status_code=400)

        output_dir = (data.get("output_dir") or "").strip()
        skip_qa = bool(data.get("skip_qa", False))
        skip_build = bool(data.get("skip_build", False))

        from .. import config
        if not config.CLOW_CLONE_ENABLED:
            return _JR({"error": "Website cloner desabilitado (CLOW_CLONE_ENABLED=false)"}, status_code=403)

        job_id = _new_job(
            user_id=sess.get("user_id", 0),
            url=url,
            output_dir=output_dir,
            skip_qa=skip_qa,
            skip_build=skip_build,
        )
        _EXECUTOR.submit(_run_job, job_id)

        return _JR({"job_id": job_id, "status": "queued"}, status_code=202)

    @app.get("/api/v1/clone/jobs/{job_id}", tags=["clone"])
    async def get_clone_job(job_id: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        with _JOBS_LOCK:
            job = dict(_JOBS.get(job_id, {}))
        if not job:
            return _JR({"error": "Job nao encontrado"}, status_code=404)
        if job.get("user_id") != sess.get("user_id") and not sess.get("is_admin"):
            return _JR({"error": "Sem permissao"}, status_code=403)
        return _JR(job)

    @app.get("/api/v1/clone/jobs", tags=["clone"])
    async def list_clone_jobs(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        uid = sess.get("user_id")
        with _JOBS_LOCK:
            jobs = [
                {
                    "job_id": j["job_id"],
                    "url": j["url"],
                    "status": j["status"],
                    "created_at": j["created_at"],
                    "finished_at": j.get("finished_at"),
                    "progress_count": len(j.get("progress", [])),
                }
                for j in _JOBS.values()
                if j.get("user_id") == uid or sess.get("is_admin")
            ]
        return _JR({"jobs": sorted(jobs, key=lambda x: x["created_at"], reverse=True)})
