"""Settings and model routes (`AGENTS.md` Section 12.5).

The surface that lets a user turn the semantic layer on. Two shape decisions
are worth stating, because neither is obvious from the path list alone.

**`repository_id` is required.** Section 12.5 writes the paths without
parameters, but ADR-0009 decision 5 makes the provider choice per repository.
A settings call with no repository would have to invent a default scope, and
inventing a default scope for a privacy setting is exactly the wrong instinct.

**PATCH bodies use `null` for "clear" and omission for "leave alone".** The
service needs both, and JSON gives us the distinction for free as long as the
model records which keys were actually sent.

No response here carries a credential, because none of the models has a field
one could occupy.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from codeatlas.api.routers.repositories import Services
from codeatlas.application.embedding_migrations import EmbeddingMigrationView
from codeatlas.domain.semantic import AnswerProviderKind, EmbeddingProviderKind

router = APIRouter(tags=["settings"])

RepositoryId = Annotated[str, Query(min_length=1, max_length=128)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettingsResponse(StrictModel):
    repository_id: str
    embedding_provider: str
    monthly_token_budget: int | None
    per_run_token_budget: int | None
    # Surfaced explicitly rather than left for the client to infer from the
    # provider name. It is the single most important fact on a settings page,
    # and a client that had to maintain its own list of which providers
    # transmit would eventually disagree with the server.
    transmits_off_machine: bool
    updated_at: str
    # The second provider decision. Reported separately from the embedding one
    # because the two are independent: a repository may retrieve locally and
    # answer remotely, or the reverse.
    answer_provider: str
    answer_model: str | None
    answer_timeout_seconds: int | None


class UpdateSettingsBody(StrictModel):
    """A partial change. An unmentioned field is left alone.

    ``monthly_token_budget: null`` means *clear it*, which is a different
    request from not mentioning it — so the handler inspects
    ``model_fields_set`` rather than reading the value.
    """

    embedding_provider: EmbeddingProviderKind | None = None
    monthly_token_budget: int | None = Field(default=None, ge=0)
    per_run_token_budget: int | None = Field(default=None, ge=0)
    answer_provider: AnswerProviderKind | None = None
    answer_model: str | None = Field(default=None, min_length=1, max_length=200)
    answer_timeout_seconds: int | None = Field(default=None, ge=1, le=3600)


class ModelResponse(StrictModel):
    provider: str
    model_id: str | None
    dimensions: int | None
    available: bool
    transmits_off_machine: bool
    requires: str | None


class AnswerModelResponse(StrictModel):
    """One answer provider a user could choose, and what choosing it means.

    Deliberately not merged into `ModelResponse`: an answer model has no
    dimensions, and a field that is always null teaches a client the wrong
    shape.
    """

    provider: str
    model_id: str | None
    available: bool
    transmits_off_machine: bool
    requires: str | None


class ModelsResponse(StrictModel):
    models: list[ModelResponse]
    # Additive, so a client written before answer generation keeps working.
    answer_models: list[AnswerModelResponse] = Field(default_factory=list)


class ProviderTestResponse(StrictModel):
    provider: str
    ok: bool
    detail_code: str | None
    latency_ms: int


class CreateEmbeddingMigrationBody(StrictModel):
    repository_id: str = Field(min_length=1, max_length=128)


class ActivateEmbeddingMigrationBody(StrictModel):
    target: Literal["target", "source"] = "target"


class EmbeddingMigrationResponse(StrictModel):
    migration_id: str
    repository_id: str
    status: str
    source_namespace_id: str
    target_namespace_id: str
    active_namespace_id: str | None
    snapshot_id: str | None
    source_coverage: float | None
    target_coverage: float | None
    target_total_count: int | None
    target_embedded_count: int | None
    target_pending_count: int | None
    target_failed_count: int | None
    target_model_id: str
    target_dimensions: int
    target_normalization_version: str
    failure_code: str | None
    created_at: str
    updated_at: str
    activated_at: str | None
    rolled_back_at: str | None


@router.get("/v1/settings")
def get_settings(
    services: Services, repository_id: RepositoryId
) -> SettingsResponse:
    return _settings_response(services.settings.get(repository_id))


@router.patch("/v1/settings")
def update_settings(
    services: Services, repository_id: RepositoryId, body: UpdateSettingsBody
) -> SettingsResponse:
    sent = body.model_fields_set
    return _settings_response(
        services.settings.update(
            repository_id,
            embedding_provider=body.embedding_provider,
            monthly_token_budget=body.monthly_token_budget,
            per_run_token_budget=body.per_run_token_budget,
            # An explicit `null` is a clear; an absent key is not.
            clear_monthly=(
                "monthly_token_budget" in sent and body.monthly_token_budget is None
            ),
            clear_per_run=(
                "per_run_token_budget" in sent and body.per_run_token_budget is None
            ),
            answer_provider=body.answer_provider,
            answer_model=body.answer_model,
            answer_timeout_seconds=body.answer_timeout_seconds,
        )
    )


@router.get("/v1/models")
def list_models(services: Services) -> ModelsResponse:
    """Every provider, including those that cannot run on this machine.

    Hiding an unavailable option would leave a user unable to discover that
    installing an extra is all that stands between them and the feature.
    """
    return ModelsResponse(
        models=[
            ModelResponse(
                provider=model.provider.value,
                model_id=model.model_id,
                dimensions=model.dimensions,
                available=model.available,
                transmits_off_machine=model.transmits_off_machine,
                requires=model.requires,
            )
            for model in services.settings.models()
        ],
        answer_models=[
            AnswerModelResponse(
                provider=model.provider.value,
                model_id=model.model_id,
                available=model.available,
                transmits_off_machine=model.transmits_off_machine,
                requires=model.requires,
            )
            for model in services.settings.answer_models()
        ],
    )


@router.post("/v1/models/test")
def test_model(
    services: Services, repository_id: RepositoryId
) -> ProviderTestResponse:
    """Ask the configured provider to embed one fixed probe string.

    A failure is reported in the body with `ok: false`, not as an HTTP error:
    the request succeeded, and what it discovered is that the provider does not
    work. Returning 5xx would make a client retry a question that has already
    been answered.
    """
    result = services.settings.test_provider(repository_id)
    return ProviderTestResponse(
        provider=result.provider.value,
        ok=result.ok,
        detail_code=result.detail_code,
        latency_ms=result.latency_ms,
    )


@router.post("/v1/models/embedding-migrations")
def start_embedding_migration(
    services: Services, body: CreateEmbeddingMigrationBody
) -> EmbeddingMigrationResponse:
    """Backfill the configured model in a shadow namespace.

    The active namespace keeps serving until the caller explicitly activates
    the migration. That keeps model changes reversible and makes partial
    backfills visible instead of hidden behind a setting flip.
    """
    return _migration_response(
        services.embedding_migrations.start(body.repository_id)
    )


@router.get("/v1/models/embedding-migrations/{migration_id}")
def get_embedding_migration(
    services: Services, migration_id: str
) -> EmbeddingMigrationResponse:
    return _migration_response(services.embedding_migrations.get(migration_id))


@router.post("/v1/models/embedding-migrations/{migration_id}/activate")
def activate_embedding_migration(
    services: Services,
    migration_id: str,
    body: ActivateEmbeddingMigrationBody | None = None,
) -> EmbeddingMigrationResponse:
    resolved = body or ActivateEmbeddingMigrationBody()
    return _migration_response(
        services.embedding_migrations.activate(
            migration_id, target=resolved.target
        )
    )


def _settings_response(settings: object) -> SettingsResponse:
    return SettingsResponse(
        repository_id=settings.repository_id,  # type: ignore[attr-defined]
        embedding_provider=settings.embedding_provider.value,  # type: ignore[attr-defined]
        monthly_token_budget=settings.monthly_token_budget,  # type: ignore[attr-defined]
        per_run_token_budget=settings.per_run_token_budget,  # type: ignore[attr-defined]
        transmits_off_machine=settings.transmits_off_machine,  # type: ignore[attr-defined]
        updated_at=settings.updated_at.isoformat(),  # type: ignore[attr-defined]
        answer_provider=settings.answer_provider.value,  # type: ignore[attr-defined]
        answer_model=settings.answer_model,  # type: ignore[attr-defined]
        answer_timeout_seconds=settings.answer_timeout_seconds,  # type: ignore[attr-defined]
    )


def _migration_response(
    migration: EmbeddingMigrationView,
) -> EmbeddingMigrationResponse:
    return EmbeddingMigrationResponse(
        migration_id=migration.migration_id,
        repository_id=migration.repository_id,
        status=migration.status,
        source_namespace_id=migration.source_namespace_id,
        target_namespace_id=migration.target_namespace_id,
        active_namespace_id=migration.active_namespace_id,
        snapshot_id=migration.snapshot_id,
        source_coverage=migration.source_coverage,
        target_coverage=migration.target_coverage,
        target_total_count=migration.target_total_count,
        target_embedded_count=migration.target_embedded_count,
        target_pending_count=migration.target_pending_count,
        target_failed_count=migration.target_failed_count,
        target_model_id=migration.target_model_id,
        target_dimensions=migration.target_dimensions,
        target_normalization_version=migration.target_normalization_version,
        failure_code=migration.failure_code,
        created_at=migration.created_at.isoformat(),
        updated_at=migration.updated_at.isoformat(),
        activated_at=(
            migration.activated_at.isoformat()
            if migration.activated_at
            else None
        ),
        rolled_back_at=(
            migration.rolled_back_at.isoformat()
            if migration.rolled_back_at
            else None
        ),
    )
