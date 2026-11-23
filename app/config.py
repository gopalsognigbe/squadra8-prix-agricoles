"""Lit les variables d'environnement (fichier .env).

Responsable : Gopal.
"""

from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Paramètres de l'application, lus depuis l'environnement."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://squadra8:squadra8@localhost:5432/prix_agricoles"

    # IA principale : Groq (ou tout fournisseur compatible OpenAI).
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GROQ_API_KEY", "OPENAI_API_KEY"),
    )
    openai_base_url: str = "https://api.groq.com/openai/v1"
    openai_model: str = Field(
        default="openai/gpt-oss-120b",
        validation_alias=AliasChoices("OPENAI_MODEL", "LLM_MODEL"),
    )
    # Pour les modèles « reasoning » Groq (gpt-oss-*) : low | medium | high.
    llm_reasoning_effort: str | None = None

    # 2e secours : Gemini (API compatible OpenAI), optionnel.
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_model: str = "gemini-3.5-flash-lite"

    # Secours Azure (optionnel).
    azure_openai_endpoint: str = ""
    azure_openai_key: str = ""
    azure_openai_deployment: str = "gpt-4.1-mini"

    fernet_key: str = ""
    hash_pepper: str = ""
    admin_email: str = ""
    admin_password_initial: str = ""
    question_voix_active: bool = True
    whisper_modele: str = "small"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Mise à jour FAO (API FPMA) au démarrage, en tâche de fond.
    maj_fao_au_demarrage: bool = True
    maj_fao_tout_benin: bool = False

    @model_validator(mode="after")
    def _groq_defaults(self) -> "Settings":
        # Clé Groq (gsk_…) sans base URL explicite → endpoint Groq.
        if (
            "openai_base_url" not in self.model_fields_set
            and self.openai_api_key.startswith("gsk_")
        ):
            self.openai_base_url = "https://api.groq.com/openai/v1"
        return self


@lru_cache
def get_settings() -> Settings:
    """Retourne les paramètres (lus une seule fois)."""
    return Settings()
