"""Démarre FastAPI et branche les routes.

Responsable : Gopal.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api import admin, ia, prix, sim, twilio
from app.config import get_settings
from app.voix.piper_tts import PiperTTS
from data.scripts.maj_fao import lancer_maj_fao

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lance la maj FAO en arrière-plan sans bloquer /sante."""
    settings = get_settings()
    tache: asyncio.Task[None] | None = None

    if settings.maj_fao_au_demarrage:
        async def _maj_fond() -> None:
            try:
                await asyncio.to_thread(
                    lancer_maj_fao,
                    tout_benin=settings.maj_fao_tout_benin,
                )
            except Exception:  # noqa: BLE001 — le démarrage ne doit jamais planter
                logger.exception("Maj FAO en fond : échec inattendu, l'app continue")

        tache = asyncio.create_task(_maj_fond())
        logger.info("Maj FAO planifiée en tâche de fond (MAJ_FAO_AU_DEMARRAGE=true)")
    else:
        logger.info("Maj FAO au démarrage désactivée (MAJ_FAO_AU_DEMARRAGE=false)")

    yield

    if tache is not None and not tache.done():
        tache.cancel()
        try:
            await tache
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Squadra 8 – Prix agricoles",
    description="Service téléphonique de prix agricoles pour les producteurs du Zou.",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.settings = get_settings()
_admin_dir = Path(__file__).resolve().parents[1] / "web" / "admin"
if _admin_dir.is_dir():
    app.mount("/admin", StaticFiles(directory=_admin_dir, html=True), name="admin")
class _SansCache(StaticFiles):
    """Le navigateur recharge toujours la page : jamais d'ancienne version en démo."""

    async def get_response(self, path, scope):
        reponse = await super().get_response(path, scope)
        reponse.headers["Cache-Control"] = "no-store"
        return reponse


_sim_dir = Path(__file__).resolve().parents[1] / "web" / "simulateur"
if _sim_dir.is_dir():
    app.mount("/simulateur", _SansCache(directory=_sim_dir, html=True), name="simulateur")
# Clips de voix (Piper) : voix/clips, ou VOIX_CLIPS_DIR. Dossier ignoré par Git.
_clips_dir = PiperTTS().dossier_clips
try:
    _clips_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/audio", StaticFiles(directory=_clips_dir), name="audio")
except OSError:
    logger.warning("Dossier des clips inaccessible : %s (pas de /audio)", _clips_dir)

app.include_router(sim.router, prefix="/api/sim", tags=["simulateur"])
app.include_router(prix.router, prefix="/api", tags=["prix"])
app.include_router(ia.router, prefix="/api/ia", tags=["ia"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(twilio.router, prefix="/twilio", tags=["twilio"])


@app.get("/", include_in_schema=False)
def accueil() -> RedirectResponse:
    """La racine ouvre le simulateur (démo)."""
    return RedirectResponse("/simulateur/")


@app.get("/sante")
def sante() -> dict[str, str]:
    """Indique que l'application répond."""
    return {"statut": "ok"}


@app.get("/health")
def health() -> dict[str, bool]:
    """Même chose que /sante, au format prévu par le plan (/health → {"ok": true})."""
    return {"ok": True}
