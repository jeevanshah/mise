from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.api.routes.onboarding import router as onboarding_router
from app.core.config import settings

app = FastAPI(title="Mise API", version="0.1.0")

app.include_router(auth_router)
app.include_router(onboarding_router)


@app.get("/health")
def health() -> dict:
    """Liveness/readiness check for CI and deploy tooling — no DB round-trip
    yet, kept deliberately trivial until there's a real endpoint to test
    the DB connection through."""
    return {"status": "ok", "environment": settings.environment}


# Routers for staff/stations, suppliers/ingredients/menu/equipment etc. are
# added from Epic 1 step 6 onward, now that auth/Membership (step 4) and
# onboarding (step 5) exist to build on.
