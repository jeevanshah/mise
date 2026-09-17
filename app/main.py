from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.api.routes.catalog import router as catalog_router
from app.api.routes.onboarding import router as onboarding_router
from app.api.routes.service_days import router as service_days_router
from app.api.routes.staffing import router as staffing_router
from app.core.config import settings

app = FastAPI(title="Mise API", version="0.1.0")

app.include_router(auth_router)
app.include_router(onboarding_router)
app.include_router(staffing_router)
app.include_router(catalog_router)
app.include_router(service_days_router)


@app.get("/health")
def health() -> dict:
    """Liveness/readiness check for CI and deploy tooling — no DB round-trip
    yet, kept deliberately trivial until there's a real endpoint to test
    the DB connection through."""
    return {"status": "ok", "environment": settings.environment}


# Epic 1 is now complete (steps 1-9). Epic 2 (Kitchen Roster) is next, and
# is gated on confirming the service-period question with the customer —
# see the epics doc.
