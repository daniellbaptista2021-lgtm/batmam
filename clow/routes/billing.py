"""Billing routes — Stripe checkout, portal, webhook, status."""

from __future__ import annotations
from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR


def register_billing_routes(app) -> None:

    from .auth import _get_user_session

    @app.get("/checkout/{plan_id}", tags=["billing"])
    async def public_checkout(plan_id: str, request: _Req):
        """Checkout publico — cartao + boleto (assinatura recorrente)."""
        if plan_id not in ("lite", "starter", "pro", "business"):
            return _JR({"error": "Plano invalido"}, status_code=400)

        from ..billing import create_public_checkout
        result = create_public_checkout(
            plan_id=plan_id,
            success_url="https://clow.pvcorretor01.com.br/signup?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://clow.pvcorretor01.com.br/landing",
        )
        if result.get("url"):
            from starlette.responses import RedirectResponse
            return RedirectResponse(result["url"])
        return _JR(result, status_code=400)

    @app.get("/checkout/{plan_id}/pix", tags=["billing"])
    async def public_checkout_pix(plan_id: str, request: _Req):
        """Checkout publico via PIX — pagamento unico, ativa por 30 dias."""
        if plan_id not in ("lite", "starter", "pro", "business"):
            return _JR({"error": "Plano invalido"}, status_code=400)

        from ..billing import create_public_checkout
        result = create_public_checkout(
            plan_id=plan_id,
            success_url="https://clow.pvcorretor01.com.br/signup?session_id={CHECKOUT_SESSION_ID}&method=pix",
            cancel_url="https://clow.pvcorretor01.com.br/landing",
            payment_mode="pix",
        )
        if result.get("url"):
            from starlette.responses import RedirectResponse
            return RedirectResponse(result["url"])
        return _JR(result, status_code=400)

    @app.post("/api/v1/billing/checkout", tags=["billing"])
    async def billing_checkout(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        body = await request.json()
        plan_id = body.get("plan_id", "")

        if plan_id not in ("lite", "starter", "pro", "business"):
            return _JR({"error": "Plano invalido"}, status_code=400)

        from ..billing import create_checkout_session
        result = create_checkout_session(
            user_id=sess["user_id"],
            email=sess["email"],
            plan_id=plan_id,
            success_url=body.get("success_url", ""),
            cancel_url=body.get("cancel_url", ""),
        )
        return _JR(result)

    @app.post("/api/v1/billing/portal", tags=["billing"])
    async def billing_portal(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        from ..database import get_user_by_id
        user = get_user_by_id(sess["user_id"])
        customer_id = user.get("stripe_customer_id", "") if user else ""
        if not customer_id:
            return _JR({"error": "Nenhuma assinatura ativa"}, status_code=400)

        from ..billing import create_portal_session
        body = await request.json()
        result = create_portal_session(customer_id, body.get("return_url", ""))
        return _JR(result)

    @app.get("/api/v1/billing/status", tags=["billing"])
    async def billing_status(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        from ..billing import get_billing_status
        return _JR(get_billing_status(sess["user_id"]))

    @app.post("/api/v1/billing/webhook", tags=["billing"], include_in_schema=False)
    async def billing_webhook(request: _Req):
        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")

        from ..billing import handle_webhook
        result = handle_webhook(payload, sig)
        if "error" in result:
            return _JR(result, status_code=400)
        return _JR(result)
