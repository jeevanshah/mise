from fastapi import FastAPI

from app.api.routes.attendance import router as attendance_router
from app.api.routes.auth import router as auth_router
from app.api.routes.capture import router as capture_router
from app.api.routes.catalog import router as catalog_router
from app.api.routes.chef_brief import router as chef_brief_router
from app.api.routes.handover import router as handover_router
from app.api.routes.kitchen_memory import router as kitchen_memory_router
from app.api.routes.notification import router as notification_router
from app.api.routes.onboarding import router as onboarding_router
from app.api.routes.pilot_metrics import router as pilot_metrics_router
from app.api.routes.prep import router as prep_router
from app.api.routes.purchase_order import router as purchase_order_router
from app.api.routes.roster import router as roster_router
from app.api.routes.service_days import router as service_days_router
from app.api.routes.staffing import router as staffing_router
from app.core.config import settings

app = FastAPI(title="Mise API", version="0.1.0")

app.include_router(auth_router)
app.include_router(onboarding_router)
app.include_router(staffing_router)
app.include_router(catalog_router)
app.include_router(service_days_router)
app.include_router(roster_router)
app.include_router(attendance_router)
app.include_router(prep_router)
app.include_router(purchase_order_router)
app.include_router(capture_router)
app.include_router(handover_router)
app.include_router(chef_brief_router)
app.include_router(kitchen_memory_router)
app.include_router(notification_router)
app.include_router(pilot_metrics_router)


@app.get("/health")
def health() -> dict:
    """Liveness/readiness check for CI and deploy tooling — no DB round-trip
    yet, kept deliberately trivial until there's a real endpoint to test
    the DB connection through."""
    return {"status": "ok", "environment": settings.environment}


# Epics 1-11 are complete — the full locked Rev 4 build order.
