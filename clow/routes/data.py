"""Data Routes — backup, export, import, delete."""

from __future__ import annotations

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, Response


def register_data_routes(app) -> None:

    from .auth import _get_user_session

    def _auth(request: _Req):
        return _get_user_session(request)

    def _tenant(sess: dict) -> str:
        return sess["user_id"]

    @app.get("/api/v1/data/export/all", tags=["data"])
    async def data_export_all(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..backup_export import export_all
        data = export_all(_tenant(sess))
        return Response(content=data, media_type="application/zip",
                       headers={"Content-Disposition": "attachment; filename=clow-export.zip"})

    @app.get("/api/v1/data/export/leads/csv", tags=["data"])
    async def data_export_csv(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..backup_export import export_leads_csv
        instance_id = request.query_params.get("instance_id", "")
        csv_data = export_leads_csv(_tenant(sess), instance_id)
        return Response(content=csv_data, media_type="text/csv",
                       headers={"Content-Disposition": "attachment; filename=leads.csv"})

    @app.get("/api/v1/data/export/leads/json", tags=["data"])
    async def data_export_json(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..backup_export import export_leads_json
        return _JR(export_leads_json(_tenant(sess)))

    @app.get("/api/v1/data/export/conversations", tags=["data"])
    async def data_export_convs(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..backup_export import export_conversations
        return _JR(export_conversations(_tenant(sess)))

    @app.post("/api/v1/data/import/leads", tags=["data"])
    async def data_import_leads(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        form = await request.form()
        file = form.get("file")
        instance_id = form.get("instance_id", "")
        if not file:
            return _JR({"error": "Arquivo CSV obrigatorio"}, status_code=400)
        content = (await file.read()).decode("utf-8-sig")
        from ..backup_export import import_leads_csv
        return _JR(import_leads_csv(_tenant(sess), instance_id, content))

    @app.get("/api/v1/data/backups", tags=["data"])
    async def data_list_backups(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..backup_export import list_backups
        return _JR({"backups": list_backups(_tenant(sess))})

    @app.post("/api/v1/data/backups/create", tags=["data"])
    async def data_create_backup(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..backup_export import create_backup
        return _JR(create_backup(_tenant(sess)))

    @app.get("/api/v1/data/backups/{filename}/download", tags=["data"])
    async def data_download_backup(filename: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..backup_export import get_backup_file
        data = get_backup_file(_tenant(sess), filename)
        if not data:
            return _JR({"error": "Backup nao encontrado"}, status_code=404)
        return Response(content=data, media_type="application/zip",
                       headers={"Content-Disposition": f"attachment; filename={filename}"})

    @app.post("/api/v1/data/delete-all", tags=["data"])
    async def data_delete_all(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        if not sess.get("is_admin") and not sess.get("is_owner", True):
            return _JR({"error": "Apenas o proprietario pode excluir dados"}, status_code=403)
        body = await request.json()
        if body.get("confirmation") != "EXCLUIR TUDO":
            return _JR({"error": "Digite EXCLUIR TUDO para confirmar"}, status_code=400)
        from ..backup_export import delete_all_data
        return _JR(delete_all_data(_tenant(sess)))
