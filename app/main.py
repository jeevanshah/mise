from fastapi import FastAPI

from app.api.routes.attendance import router as attendance_router
from app.api.routes.auth import router as auth_router
from app.api.routes.capture import router as capture_router
from app.api.routes.catalog import router as catalog_router
from app.api.routes.onboarding import router as onboarding_router
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


@app.get("/health")
def health() -> dict:
    """Liveness/readiness check for CI and deploy tooling — no DB round-trip
    yet, kept deliberately trivial until there's a real endpoint to test
    the DB connection through."""
    return {"status": "ok", "environment": settings.environment}


# Epics 1-6 are complete. Epic 7 (Handover) is next per the locked
# build order.
