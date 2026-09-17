from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.core.config import settings

app = FastAPI(title="Mise API", version="0.1.0")

app.include_router(auth_router)


@app.get("/health")
def health() -> dict:
    """Liveness/readiness check for CI and deploy tooling — no DB round-trip
    yet, kept deliberately trivial until there's a real endpoint to test
    the DB connection through."""
    return {"status": "ok", "environment": settings.environment}


# Routers for onboarding, staff/stations, suppliers/ingredients etc. are
# added from Epic 1 step 5 onward, now that auth/Membership (step 4) exists
# to protect them via app.api.deps.require_membership.
