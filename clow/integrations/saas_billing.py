"""SaaS billing and subscription management via Stripe."""
import logging
import os

logger = logging.getLogger(__name__)
STRIPE_KEY = os.getenv("STRIPE_SECRET_KEY", "")


def is_available() -> bool:
    try:
        import stripe
        return bool(STRIPE_KEY)
    except ImportError:
        return False


class BillingManager:
    def __init__(self):
        self._stripe = None
        if STRIPE_KEY:
            try:
                import stripe
                stripe.api_key = STRIPE_KEY
                self._stripe = stripe
            except ImportError:
                pass

    def create_checkout(self, email: str, plan: str = "pro") -> dict:
        if not self._stripe:
            return {"error": "Stripe not configured. Set STRIPE_SECRET_KEY."}
        prices = {
            "pro": os.getenv("STRIPE_PRICE_PRO", ""),
            "unlimited": os.getenv("STRIPE_PRICE_UNLIMITED", ""),
        }
        price_id = prices.get(plan)
        if not price_id:
            return {"error": f"Price not configured for plan: {plan}"}
        try:
            session = self._stripe.checkout.Session.create(
                customer_email=email,
                payment_method_types=["card"],
                line_items=[{"price": price_id, "quantity": 1}],
                mode="subscription",
                success_url=os.getenv("CLOW_URL", "https://clow.pvcorretor01.com.br") + "/billing/success",
                cancel_url=os.getenv("CLOW_URL", "https://clow.pvcorretor01.com.br") + "/billing/cancel",
            )
            return {"url": session.url, "session_id": session.id}
        except Exception as e:
            return {"error": str(e)}

    def get_subscription(self, email: str) -> dict:
        if not self._stripe:
            return {"plan": "free", "status": "no_billing"}
        try:
            custs = self._stripe.Customer.list(email=email, limit=1)
            if not custs.data:
                return {"plan": "free", "status": "no_customer"}
            subs = self._stripe.Subscription.list(customer=custs.data[0].id, status="active", limit=1)
            if not subs.data:
                return {"plan": "free", "status": "no_subscription"}
            return {"plan": "pro", "status": "active", "period_end": subs.data[0].current_period_end}
        except Exception as e:
            return {"plan": "free", "error": str(e)}


billing = BillingManager()
