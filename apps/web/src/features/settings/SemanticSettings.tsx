/**
 * Provider settings for one repository.
 *
 * This is the only screen in CodeAtlas where a user can cause repository
 * content to leave their machine. The layout keeps that consequence visible in
 * the same place as the decision: every provider option states its transmission
 * boundary in words, unavailable options remain visible with their requirement,
 * and any off-machine choice reveals the required budget before save.
 */

import { type FormEvent, useEffect, useState } from "react";

import { Skeleton } from "../../components/Skeleton";
import type { AnswerModel, EmbeddingModel } from "../../lib/queries";
import {
  useModels,
  usePullOllamaModel,
  useValidateEmbeddingModel,
  useSemanticStatus,
  useSettings,
  useTestProvider,
  useUpdateSettings,
} from "../../lib/queries";

interface Props {
  readonly repositoryId: string;
}

type ProviderModel = EmbeddingModel | AnswerModel;

const PROVIDER_LABELS: Record<string, string> = {
  none: "Disabled",
  local: "Local model",
  openai: "OpenAI",
};

const ANSWER_PROVIDER_LABELS: Record<string, string> = {
  none: "No answer generation",
  ollama: "Ollama (local, recommended)",
  openai: "OpenAI",
};

export function SemanticSettings({ repositoryId }: Props) {
  const settings = useSettings(repositoryId);
  const models = useModels();
  const status = useSemanticStatus(repositoryId);
  const update = useUpdateSettings(repositoryId);
  const test = useTestProvider(repositoryId);
  const pullOllama = usePullOllamaModel();
  const validateModel = useValidateEmbeddingModel();

  const [provider, setProvider] = useState<string>("none");
  const [monthlyBudget, setMonthlyBudget] = useState<string>("");
  const [answerProvider, setAnswerProvider] = useState<string>("none");
  const [answerModel, setAnswerModel] = useState<string>("");
  const [embeddingModel, setEmbeddingModel] = useState<string>("");
  // The model id proven to load. Reset whenever the field changes, because a
  // checked id and an edited one are not the same id.
  const [validatedModel, setValidatedModel] = useState<string | null>(null);

  useEffect(() => {
    if (settings.data) {
      setProvider(settings.data.embedding_provider);
      setMonthlyBudget(
        settings.data.monthly_token_budget === null
          ? ""
          : String(settings.data.monthly_token_budget),
      );
      setAnswerProvider(settings.data.answer_provider ?? "none");
      setAnswerModel(settings.data.answer_model ?? "");
      setEmbeddingModel(settings.data.embedding_model ?? "");
      setValidatedModel(settings.data.embedding_model ?? null);
    }
  }, [settings.data]);

  if (
    settings.isLoading ||
    models.isLoading ||
    !settings.isFetchedAfterMount ||
    !models.isFetchedAfterMount
  ) {
    return (
      <div className="grid gap-[var(--space-4)] lg:grid-cols-3">
        <Skeleton className="h-28" label="Loading provider settings" />
        <Skeleton className="h-28" label="Loading model settings" />
        <Skeleton className="h-28" label="Loading privacy settings" />
      </div>
    );
  }

  if (settings.isError || models.isError) {
    return (
      <div
        role="alert"
        className="rounded-[var(--radius-md)] border border-danger bg-surface p-[var(--space-4)] text-sm text-danger"
      >
        Settings could not be loaded. The backend may not be running.
      </div>
    );
  }

  const embeddingModels = models.data?.models ?? [];
  const answerModels = models.data?.answer_models ?? [];
  const chosen = embeddingModels.find((item) => item.provider === provider);
  const chosenAnswer = answerModels.find(
    (item) => item.provider === answerProvider,
  );
  const transmits =
    (chosen?.transmits_off_machine ?? false) ||
    (chosenAnswer?.transmits_off_machine ?? false);
  const trimmedEmbeddingModel = embeddingModel.trim();
  // A blank field means "use the configured default", which needs no check.
  // Everything else must be proven to load before it can be saved: the vector
  // index is labelled with the model's width, and a wrong label never raises.
  const embeddingModelReady =
    provider !== "local" ||
    trimmedEmbeddingModel === "" ||
    trimmedEmbeddingModel === validatedModel;
  const selectedOllamaModel =
    answerModel.trim() || chosenAnswer?.model_id?.trim() || "";

  function save(event: FormEvent) {
    event.preventDefault();
    const parsed = monthlyBudget.trim() === "" ? null : Number(monthlyBudget);
    const trimmedModel = answerModel.trim();
    update.mutate({
      embedding_provider: provider,
      monthly_token_budget: parsed,
      answer_provider: answerProvider,
      answer_model: trimmedModel === "" ? null : trimmedModel,
      embedding_model:
        provider === "local" && trimmedEmbeddingModel !== ""
          ? trimmedEmbeddingModel
          : null,
    });
  }

  return (
    <section
      aria-labelledby="semantic-settings-heading"
      className="space-y-[var(--space-8)]"
    >
      <div className="flex flex-col gap-[var(--space-3)] md:flex-row md:items-start md:justify-between">
        <div>
          <h2
            id="semantic-settings-heading"
            className="text-xl font-semibold tracking-tight"
          >
            Semantic search
          </h2>
          <p className="mt-[var(--space-2)] max-w-3xl text-sm text-text-muted">
            Semantic search is optional. CodeAtlas answers with exact, lexical,
            graph, and Git retrieval whether or not it is enabled.
          </p>
        </div>
        <StatusPill tone={transmits ? "warning" : "fresh"}>
          {transmits
            ? "Off-machine provider selected"
            : "Local-only configuration"}
        </StatusPill>
      </div>

      <div className="grid gap-[var(--space-3)] lg:grid-cols-3">
        <SummaryPanel
          label="Embeddings"
          value={PROVIDER_LABELS[provider] ?? provider}
          detail={chosen?.model_id ?? "No embedding model selected"}
        />
        <SummaryPanel
          label="Answer writing"
          value={ANSWER_PROVIDER_LABELS[answerProvider] ?? answerProvider}
          detail={chosenAnswer?.model_id ?? "Template answers"}
        />
        <SummaryPanel
          label="Repository content"
          value={
            transmits
              ? "Sends repository content off this machine"
              : "Stays on this machine"
          }
          detail={
            transmits
              ? "A monthly token budget is required."
              : "No transmitting provider is selected."
          }
          tone={transmits ? "warning" : "fresh"}
        />
      </div>

      <form
        onSubmit={save}
        className="grid gap-[var(--space-8)] xl:grid-cols-[minmax(0,1fr)_20rem]"
      >
        <div className="space-y-[var(--space-8)]">
          <fieldset className="space-y-[var(--space-3)]">
            <legend className="text-base font-semibold">
              Embedding provider
            </legend>
            <p className="text-sm text-text-muted">
              Choose the retrieval layer used for semantic candidates.
            </p>
            <div className="grid gap-[var(--space-3)] md:grid-cols-3">
              {embeddingModels.map((model) => (
                <ProviderOption
                  key={model.provider}
                  id={`provider-${model.provider}`}
                  name="embedding-provider"
                  label={PROVIDER_LABELS[model.provider] ?? model.provider}
                  model={model}
                  checked={provider === model.provider}
                  detail={embeddingDetail(model)}
                  onChoose={() => setProvider(model.provider)}
                />
              ))}
            </div>
          </fieldset>

          <fieldset className="space-y-[var(--space-3)]">
            <legend className="text-base font-semibold">Answer provider</legend>
            <p className="text-sm text-text-muted">
              CodeAtlas finds and cites the evidence. An answer provider writes
              a prose explanation above those unchanged citations.
            </p>
            {answerModels.length > 0 ? (
              <div className="grid gap-[var(--space-3)] md:grid-cols-3">
                {answerModels.map((model) => (
                  <ProviderOption
                    key={model.provider}
                    id={`answer-provider-${model.provider}`}
                    name="answer-provider"
                    label={
                      ANSWER_PROVIDER_LABELS[model.provider] ?? model.provider
                    }
                    model={model}
                    checked={answerProvider === model.provider}
                    detail={answerDetail(model)}
                    onChoose={() => setAnswerProvider(model.provider)}
                  />
                ))}
              </div>
            ) : (
              <p className="rounded-[var(--radius-md)] border border-border bg-surface p-[var(--space-3)] text-sm text-text-muted">
                No answer providers are available in this installation.
              </p>
            )}
          </fieldset>
        </div>

        <aside className="space-y-[var(--space-4)] self-start xl:sticky xl:top-[var(--space-8)]">
          {provider === "local" ? (
            <section className="rounded-[var(--radius-md)] border border-border bg-surface p-[var(--space-4)] shadow-sm">
              <label
                htmlFor="embedding-model"
                className="block text-sm font-medium"
              >
                Embedding model
              </label>
              <input
                id="embedding-model"
                type="text"
                value={embeddingModel}
                placeholder={chosen?.model_id ?? ""}
                onChange={(event) => {
                  setEmbeddingModel(event.target.value);
                  setValidatedModel(null);
                  validateModel.reset();
                }}
                aria-describedby="embedding-model-help"
                className="mt-[var(--space-2)] w-full rounded-[var(--radius-md)] border border-border bg-surface px-[var(--space-3)] py-[var(--space-2)] text-sm"
              />
              <p
                id="embedding-model-help"
                className="mt-[var(--space-2)] text-xs leading-5 text-text-muted"
              >
                Any sentence-transformers model, for example{" "}
                <code>BAAI/bge-small-en-v1.5</code>. Leave blank to use{" "}
                {chosen?.model_id ?? "the default"}. Checking a new model
                downloads it, which can take several minutes.
              </p>
              <button
                type="button"
                onClick={() => {
                  validateModel.mutate(trimmedEmbeddingModel, {
                    onSuccess: (result) => {
                      if (result.ok) setValidatedModel(result.model_id);
                    },
                  });
                }}
                disabled={
                  validateModel.isPending || trimmedEmbeddingModel === ""
                }
                className="mt-[var(--space-3)] w-full rounded-[var(--radius-md)] border border-border px-[var(--space-3)] py-[var(--space-2)] text-sm font-medium disabled:opacity-50"
              >
                {validateModel.isPending ? "Checking..." : "Check model"}
              </button>
              {validateModel.isError ? (
                <p
                  role="alert"
                  className="mt-[var(--space-2)] text-sm text-danger"
                >
                  {(validateModel.error as Error).message}
                </p>
              ) : null}
              {validateModel.data ? (
                <p
                  role="status"
                  className={`mt-[var(--space-2)] text-sm ${
                    validateModel.data.ok ? "text-fresh" : "text-danger"
                  }`}
                >
                  {validateModel.data.ok
                    ? `${validateModel.data.model_id} loaded, ${validateModel.data.dimensions} dimensions.`
                    : `Could not load ${validateModel.data.model_id}: ${
                        validateModel.data.detail_code ?? "unknown"
                      }.`}
                </p>
              ) : null}
              {trimmedEmbeddingModel !== "" && !embeddingModelReady ? (
                <p className="mt-[var(--space-2)] text-xs leading-5 text-text-muted">
                  Check the model before saving. The vector index is labelled
                  with its width, so CodeAtlas measures it rather than guessing.
                </p>
              ) : null}
            </section>
          ) : null}

          {answerProvider !== "none" ? (
            <section className="rounded-[var(--radius-md)] border border-border bg-surface p-[var(--space-4)] shadow-sm">
              <label
                htmlFor="answer-model"
                className="block text-sm font-medium"
              >
                Answer model
              </label>
              <input
                id="answer-model"
                type="text"
                value={answerModel}
                placeholder={chosenAnswer?.model_id ?? ""}
                onChange={(event) => setAnswerModel(event.target.value)}
                aria-describedby="answer-model-help"
                className="mt-[var(--space-2)] w-full rounded-[var(--radius-md)] border border-border bg-surface px-[var(--space-3)] py-[var(--space-2)] text-sm"
              />
              <p
                id="answer-model-help"
                className="mt-[var(--space-2)] text-xs leading-5 text-text-muted"
              >
                Leave blank to use {chosenAnswer?.model_id ?? "the default"}.
                A local model must already be installed, for example{" "}
                <code>ollama pull llama3.1:8b</code>.
              </p>
              {answerProvider === "ollama" ? (
                <div className="mt-[var(--space-3)] border-t border-border pt-[var(--space-3)]">
                  <button
                    type="button"
                    onClick={() => pullOllama.mutate(selectedOllamaModel)}
                    disabled={
                      pullOllama.isPending || selectedOllamaModel.trim() === ""
                    }
                    className="w-full rounded-[var(--radius-md)] border border-border px-[var(--space-3)] py-[var(--space-2)] text-sm font-medium disabled:opacity-50"
                  >
                    {pullOllama.isPending
                      ? "Downloading..."
                      : "Download model"}
                  </button>
                  <p className="mt-[var(--space-2)] text-xs leading-5 text-text-muted">
                    Uses the model name above:{" "}
                    <code>{selectedOllamaModel || "none"}</code>.
                  </p>
                  {pullOllama.isError ? (
                    <p
                      role="alert"
                      className="mt-[var(--space-2)] text-sm text-danger"
                    >
                      {(pullOllama.error as Error).message}
                    </p>
                  ) : null}
                  {pullOllama.data ? (
                    <p
                      role="status"
                      className={`mt-[var(--space-2)] text-sm ${
                        pullOllama.data.ok ? "text-fresh" : "text-danger"
                      }`}
                    >
                      {pullOllama.data.ok
                        ? `Downloaded ${pullOllama.data.model_id}.`
                        : `Ollama could not download ${pullOllama.data.model_id}: ${
                            pullOllama.data.detail_code ?? "unknown"
                          }.`}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </section>
          ) : null}

          {transmits ? (
            <section className="rounded-[var(--radius-md)] border border-stale bg-surface p-[var(--space-4)] shadow-sm">
              <label
                htmlFor="monthly-budget"
                className="block text-sm font-medium"
              >
                Monthly token budget (required)
              </label>
              <input
                id="monthly-budget"
                type="number"
                min={0}
                value={monthlyBudget}
                onChange={(event) => setMonthlyBudget(event.target.value)}
                aria-describedby="monthly-budget-help"
                className="mt-[var(--space-2)] w-full rounded-[var(--radius-md)] border border-border bg-surface px-[var(--space-3)] py-[var(--space-2)] text-sm"
              />
              <p
                id="monthly-budget-help"
                className="mt-[var(--space-2)] text-xs leading-5 text-text-muted"
              >
                A provider that sends content off this machine cannot be
                enabled without a spending bound.
              </p>
            </section>
          ) : null}

          <section className="rounded-[var(--radius-md)] border border-border bg-surface p-[var(--space-4)] shadow-sm">
            <h3 className="text-sm font-semibold">Save changes</h3>
            <button
              type="submit"
              disabled={update.isPending || !embeddingModelReady}
              className="mt-[var(--space-3)] w-full rounded-[var(--radius-md)] bg-accent px-[var(--space-4)] py-[var(--space-2)] text-sm font-medium text-accent-contrast disabled:opacity-50"
            >
              {update.isPending ? "Saving..." : "Save"}
            </button>
            {update.isError ? (
              <p role="alert" className="mt-[var(--space-3)] text-sm text-danger">
                {(update.error as Error).message}
              </p>
            ) : null}
            {update.isSuccess ? (
              <p role="status" className="mt-[var(--space-3)] text-sm text-fresh">
                Settings saved.
              </p>
            ) : null}
          </section>
        </aside>
      </form>

      <div className="grid gap-[var(--space-4)] lg:grid-cols-2">
        <ConnectionPanel
          pending={test.isPending}
          data={test.data}
          onTest={() => test.mutate()}
        />
        <CoveragePanel repositoryId={repositoryId} status={status} />
      </div>
    </section>
  );
}

function ProviderOption({
  id,
  name,
  label,
  model,
  checked,
  detail,
  onChoose,
}: {
  readonly id: string;
  readonly name: string;
  readonly label: string;
  readonly model: ProviderModel;
  readonly checked: boolean;
  readonly detail: string;
  readonly onChoose: () => void;
}) {
  const disabled = !model.available;
  return (
    <label htmlFor={id} className={optionClass(checked, disabled)}>
      <input
        id={id}
        type="radio"
        name={name}
        value={model.provider}
        checked={checked}
        disabled={disabled}
        onChange={onChoose}
        className="mt-[2px] h-4 w-4 shrink-0 accent-accent"
      />
      <span className="min-w-0 flex-1">
        <span className="flex flex-col gap-[var(--space-2)]">
          <span className="font-medium leading-5">{label}</span>
          <TransmissionBadge transmits={model.transmits_off_machine} />
        </span>
        <span className="mt-[var(--space-2)] block text-xs leading-5 text-text-muted">
          {detail}
        </span>
        {model.requires !== null ? (
          <span className="mt-[var(--space-2)] block text-xs leading-5 text-text-muted">
            {disabled ? "Unavailable - requires " : "Requires "}
            {model.requires}
          </span>
        ) : null}
      </span>
    </label>
  );
}

function TransmissionBadge({ transmits }: { readonly transmits: boolean }) {
  return (
    <span
      className={`inline-flex w-fit rounded-[var(--radius-sm)] border px-[var(--space-2)] py-[2px] text-xs font-medium ${
        transmits
          ? "border-stale text-stale"
          : "border-border text-text-muted"
      }`}
    >
      {transmits
        ? "Sends repository content off this machine"
        : "Stays on this machine"}
    </span>
  );
}

function StatusPill({
  children,
  tone = "neutral",
}: {
  readonly children: string;
  readonly tone?: "fresh" | "neutral" | "warning";
}) {
  const toneClass =
    tone === "fresh"
      ? "border-fresh text-fresh"
      : tone === "warning"
        ? "border-stale text-stale"
        : "border-border text-text-muted";
  return (
    <span
      className={`inline-flex w-fit rounded-[var(--radius-sm)] border bg-surface px-[var(--space-2)] py-[var(--space-1)] text-xs font-medium ${toneClass}`}
    >
      {children}
    </span>
  );
}

function SummaryPanel({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  readonly label: string;
  readonly value: string;
  readonly detail: string;
  readonly tone?: "fresh" | "neutral" | "warning";
}) {
  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-[var(--space-4)] shadow-sm">
      <div className="flex items-center justify-between gap-[var(--space-3)]">
        <h3 className="text-xs font-semibold uppercase text-text-muted">
          {label}
        </h3>
        <StatusDot tone={tone} />
      </div>
      <p className="mt-[var(--space-2)] truncate text-sm font-medium">{value}</p>
      <p className="mt-[var(--space-1)] truncate text-xs text-text-muted">
        {detail}
      </p>
    </section>
  );
}

function StatusDot({
  tone,
}: {
  readonly tone: "fresh" | "neutral" | "warning";
}) {
  const color =
    tone === "fresh"
      ? "bg-fresh"
      : tone === "warning"
        ? "bg-stale"
        : "bg-text-muted";
  return <span aria-hidden="true" className={`h-2 w-2 rounded-full ${color}`} />;
}

function ConnectionPanel({
  pending,
  data,
  onTest,
}: {
  readonly pending: boolean;
  readonly data:
    | {
        readonly ok: boolean;
        readonly detail_code: string | null;
        readonly latency_ms: number;
      }
    | undefined;
  readonly onTest: () => void;
}) {
  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-[var(--space-4)] shadow-sm">
      <div className="flex items-start justify-between gap-[var(--space-4)]">
        <div>
          <h3 className="text-sm font-semibold">Connection</h3>
          <p className="mt-[var(--space-1)] text-sm text-text-muted">
            Check the selected provider path.
          </p>
        </div>
        <button
          type="button"
          onClick={onTest}
          disabled={pending}
          className="shrink-0 rounded-[var(--radius-md)] border border-border px-[var(--space-3)] py-[var(--space-2)] text-sm font-medium disabled:opacity-50"
        >
          {pending ? "Testing..." : "Test provider"}
        </button>
      </div>
      {data ? (
        <p
          role="status"
          className={`mt-[var(--space-3)] text-sm ${
            data.ok ? "text-fresh" : "text-danger"
          }`}
        >
          {data.ok
            ? `Provider responded in ${data.latency_ms} ms.`
            : `Provider did not respond: ${data.detail_code ?? "unknown"}.`}
        </p>
      ) : null}
    </section>
  );
}

function CoveragePanel({
  repositoryId,
  status,
}: {
  readonly repositoryId: string;
  readonly status: ReturnType<typeof useSemanticStatus>;
}) {
  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-[var(--space-4)] shadow-sm">
      <h3 className="text-sm font-semibold">Coverage</h3>
      {status.isPending ? (
        <p role="status" className="mt-[var(--space-2)] text-sm text-text-muted">
          Checking coverage...
        </p>
      ) : status.isError ? (
        <p role="status" className="mt-[var(--space-2)] text-sm text-stale">
          Coverage could not be read, so this page cannot say whether a
          provider is enabled. Retry, or check{" "}
          <code>codeatlas settings {repositoryId}</code>.
        </p>
      ) : status.data && status.data.coverage !== null ? (
        <CoverageValue
          coverage={status.data.coverage}
          embeddedCount={status.data.embedded_count ?? 0}
          totalCount={status.data.total_count ?? 0}
          failedCount={status.data.failed_count ?? 0}
        />
      ) : (
        <p className="mt-[var(--space-2)] text-sm text-text-muted">
          No provider is enabled, so there is nothing to cover. This is not a
          degraded state.
        </p>
      )}
    </section>
  );
}

function CoverageValue({
  coverage,
  embeddedCount,
  totalCount,
  failedCount,
}: {
  readonly coverage: number;
  readonly embeddedCount: number;
  readonly totalCount: number;
  readonly failedCount: number;
}) {
  const percent = Math.round(coverage * 100);
  return (
    <div className="mt-[var(--space-3)]">
      <div className="flex items-baseline justify-between gap-[var(--space-3)]">
        <p className="text-2xl font-semibold">{percent}%</p>
        <p className="text-xs text-text-muted">
          {embeddedCount} of {totalCount}
          {failedCount ? `, ${failedCount} failed` : ""}
        </p>
      </div>
      <div
        role="progressbar"
        aria-label="Semantic coverage"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="mt-[var(--space-3)] h-2 overflow-hidden rounded-[var(--radius-sm)] bg-surface-sunken"
      >
        <div className="h-full bg-accent" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function embeddingDetail(model: EmbeddingModel) {
  if (model.provider === "none") return "Deterministic retrieval only";
  if (model.dimensions === null) {
    return `${model.model_id ?? "Model not configured"}, dimensions auto-detected when the model loads`;
  }
  return `${model.model_id ?? "Model not configured"}, ${model.dimensions} dimensions`;
}

function answerDetail(model: AnswerModel) {
  if (model.provider === "none") return "Template answers";
  return model.model_id ?? "Model not configured";
}

function optionClass(checked: boolean, disabled: boolean) {
  const state = disabled
    ? "cursor-not-allowed opacity-60"
    : checked
      ? "border-accent bg-surface-sunken shadow-sm"
      : "border-border bg-surface hover:border-accent";
  return `flex min-h-36 gap-[var(--space-3)] rounded-[var(--radius-md)] border p-[var(--space-4)] text-sm transition-colors ${state}`;
}
