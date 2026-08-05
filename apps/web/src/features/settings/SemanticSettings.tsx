/**
 * Choosing an embedding provider for one repository.
 *
 * This is the only screen in CodeAtlas where a user can cause repository
 * content to leave their machine, so it is written to make that consequence
 * impossible to miss rather than to make the choice quick:
 *
 * - every option states whether it transmits, in words and with an icon, never
 *   by colour alone (`AGENTS.md` Section 14.4);
 * - a provider that cannot run here is shown with what it needs, not hidden —
 *   a missing option reads as a broken product;
 * - selecting a transmitting provider reveals the budget field it cannot be
 *   saved without, so the requirement is discovered before the error;
 * - the server refuses anything unsafe regardless, and its message is shown
 *   verbatim. This form is a convenience, never the control.
 */

import { useEffect, useState } from "react";

import {
  useModels,
  useSemanticStatus,
  useSettings,
  useTestProvider,
  useUpdateSettings,
} from "../../lib/queries";

interface Props {
  readonly repositoryId: string;
}

/**
 * Shared shells, so the three sections of this page read as one surface.
 *
 * Kept as constants rather than components: the markup below is deliberately
 * plain — `fieldset`, `legend`, `label`, `input` — because that is what carries
 * the accessibility contract, and wrapping each in a styled component hides
 * which element a screen reader actually meets.
 */
const PANEL =
  "rounded-[var(--radius-md)] border border-border bg-surface p-[var(--space-6)]";
const FIELD =
  "w-full rounded-[var(--radius-sm)] border border-border bg-surface-raised" +
  " px-[var(--space-3)] py-[var(--space-2)] text-sm" +
  " focus:outline-none focus:ring-2 focus:ring-accent";
const HELP = "mt-[var(--space-2)] text-xs text-text-muted";

/** One radio option, drawn as a card so the choice has a hit area and an edge. */
function optionCardClass(selected: boolean, disabled: boolean): string {
  const base =
    "flex gap-[var(--space-3)] rounded-[var(--radius-md)] border" +
    " p-[var(--space-3)] transition-colors";
  if (disabled) {
    // Shown rather than hidden — a missing option reads as a broken product —
    // but clearly not choosable.
    return `${base} cursor-not-allowed border-border bg-surface-sunken opacity-70`;
  }
  return selected
    ? `${base} cursor-pointer border-accent bg-surface-raised ring-1 ring-accent`
    : `${base} cursor-pointer border-border hover:bg-surface-raised`;
}

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

  const [provider, setProvider] = useState<string>("none");
  const [monthlyBudget, setMonthlyBudget] = useState<string>("");
  const [answerProvider, setAnswerProvider] = useState<string>("none");
  const [answerModel, setAnswerModel] = useState<string>("");

  // Reconcile from the server whenever it answers. The form is a draft of the
  // server's state, not a second copy of it (Section 14.5).
  useEffect(() => {
    if (settings.data) {
      setProvider(settings.data.embedding_provider);
      setMonthlyBudget(
        settings.data.monthly_token_budget === null
          ? ""
          : String(settings.data.monthly_token_budget),
      );
      setAnswerProvider(settings.data.answer_provider);
      setAnswerModel(settings.data.answer_model ?? "");
    }
  }, [settings.data]);

  const chosen = models.data?.models.find((item) => item.provider === provider);
  const chosenAnswer = models.data?.answer_models?.find(
    (item) => item.provider === answerProvider,
  );
  // Either decision reaching a metered account requires the budget, so the
  // field appears for either. Asking the server first would surface the
  // requirement as an error rather than as a field.
  const transmits =
    (chosen?.transmits_off_machine ?? false) ||
    (chosenAnswer?.transmits_off_machine ?? false);

  if (settings.isLoading || models.isLoading) {
    return <p role="status">Loading settings…</p>;
  }
  if (settings.isError || models.isError) {
    return (
      <p role="alert">
        Settings could not be loaded. The backend may not be running.
      </p>
    );
  }

  function save(event: React.FormEvent) {
    event.preventDefault();
    const parsed = monthlyBudget.trim() === "" ? null : Number(monthlyBudget);
    const trimmedModel = answerModel.trim();
    update.mutate({
      embedding_provider: provider,
      monthly_token_budget: parsed,
      answer_provider: answerProvider,
      // Empty means "use the configured default", which the server stores as
      // null. Sending "" would pin the repository to a nameless model.
      answer_model: trimmedModel === "" ? null : trimmedModel,
    });
  }

  return (
    <section
      aria-labelledby="semantic-settings-heading"
      className="flex flex-col gap-[var(--space-6)]"
    >
      <div className={PANEL}>
        <h2
          id="semantic-settings-heading"
          className="text-lg font-semibold tracking-tight"
        >
          Semantic search
        </h2>
        <p className="mt-[var(--space-2)] max-w-[var(--measure)] text-sm text-text-muted">
          Semantic search is optional. CodeAtlas answers with exact, lexical,
          graph, and Git retrieval whether or not it is enabled.
        </p>

        <form
          onSubmit={save}
          className="mt-[var(--space-6)] flex flex-col gap-[var(--space-6)]"
        >
          <fieldset className="border-0 p-0">
            <legend className="text-sm font-semibold">
              Embedding provider
            </legend>
            <div className="mt-[var(--space-3)] grid gap-[var(--space-2)] md:grid-cols-3">
              {models.data?.models.map((model) => (
                <label
                  key={model.provider}
                  htmlFor={`provider-${model.provider}`}
                  className={optionCardClass(
                    provider === model.provider,
                    !model.available,
                  )}
                >
                  <input
                    id={`provider-${model.provider}`}
                    type="radio"
                    name="embedding-provider"
                    value={model.provider}
                    checked={provider === model.provider}
                    disabled={!model.available}
                    onChange={() => setProvider(model.provider)}
                    className="mt-[var(--space-1)] shrink-0 accent-[var(--color-accent)]"
                  />
                  <span className="flex flex-col gap-[var(--space-1)]">
                    <span className="text-sm font-medium">
                      {PROVIDER_LABELS[model.provider] ?? model.provider}
                    </span>
                    {/* Words, not colour. Section 14.4 forbids colour alone for a
                        status this consequential. */}
                    <span className="text-xs text-text-muted">
                      {model.transmits_off_machine
                        ? "⚠ Sends repository content off this machine"
                        : "Stays on this machine"}
                    </span>
                    {!model.available && model.requires !== null ? (
                      <span className="text-xs font-medium text-text-muted">
                        Unavailable — requires {model.requires}
                      </span>
                    ) : null}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="border-0 p-0">
            <legend className="text-sm font-semibold">Answer provider</legend>
            <p className="mt-[var(--space-2)] max-w-[var(--measure)] text-sm text-text-muted">
              CodeAtlas always finds and cites the evidence itself. An answer
              provider adds a written explanation on top of it; the citations and
              their confidence never change.
            </p>
            <div className="mt-[var(--space-3)] grid gap-[var(--space-2)] md:grid-cols-3">
              {models.data?.answer_models?.map((model) => (
                <label
                  key={model.provider}
                  htmlFor={`answer-provider-${model.provider}`}
                  className={optionCardClass(
                    answerProvider === model.provider,
                    false,
                  )}
                >
                  <input
                    id={`answer-provider-${model.provider}`}
                    type="radio"
                    name="answer-provider"
                    value={model.provider}
                    checked={answerProvider === model.provider}
                    onChange={() => setAnswerProvider(model.provider)}
                    className="mt-[var(--space-1)] shrink-0 accent-[var(--color-accent)]"
                  />
                  <span className="flex flex-col gap-[var(--space-1)]">
                    <span className="text-sm font-medium">
                      {ANSWER_PROVIDER_LABELS[model.provider] ?? model.provider}
                    </span>
                    {/* Words, not colour — the same rule the embedding options obey. */}
                    <span className="text-xs text-text-muted">
                      {model.transmits_off_machine
                        ? "⚠ Sends repository content off this machine"
                        : "Stays on this machine"}
                    </span>
                    {model.requires !== null ? (
                      <span className="text-xs font-medium text-text-muted">
                        Requires {model.requires}
                      </span>
                    ) : null}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          {answerProvider !== "none" ? (
            <div className="max-w-md">
              <label
                htmlFor="answer-model"
                className="text-sm font-semibold"
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
                className={`mt-[var(--space-2)] ${FIELD}`}
              />
              <p id="answer-model-help" className={HELP}>
                Leave blank to use {chosenAnswer?.model_id ?? "the default"}. A
                larger model reasons better across files, needs more memory, and
                answers more slowly. A local model must already be installed —
                for example{" "}
                <code className="rounded-[var(--radius-sm)] bg-surface-sunken px-[var(--space-1)]">
                  ollama pull llama3.1:8b
                </code>
                .
              </p>
            </div>
          ) : null}

          {transmits ? (
            // Bordered, because this field appearing is a consequence of the
            // choice above rather than another row in the form.
            <div className="max-w-md rounded-[var(--radius-md)] border border-border bg-surface-raised p-[var(--space-4)]">
              <label
                htmlFor="monthly-budget"
                className="text-sm font-semibold"
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
                className={`mt-[var(--space-2)] ${FIELD}`}
              />
              <p id="monthly-budget-help" className={HELP}>
                A provider that sends content off this machine cannot be enabled
                without a spending bound.
              </p>
            </div>
          ) : null}

          <div>
            <button
              type="submit"
              disabled={update.isPending}
              className="rounded-[var(--radius-md)] bg-accent px-[var(--space-4)] py-[var(--space-2)] text-sm font-medium text-accent-contrast disabled:opacity-60"
            >
              {update.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </form>

        {update.isError ? (
          <p
            role="alert"
            className="mt-[var(--space-4)] rounded-[var(--radius-sm)] border border-danger px-[var(--space-3)] py-[var(--space-2)] text-sm text-danger"
          >
            {(update.error as Error).message}
          </p>
        ) : null}
        {update.isSuccess ? (
          <p
            role="status"
            className="mt-[var(--space-4)] text-sm font-medium text-text"
          >
            Settings saved.
          </p>
        ) : null}
      </div>

      <div className={PANEL}>
        <h3 className="text-base font-semibold tracking-tight">Connection</h3>
        <button
          type="button"
          onClick={() => test.mutate()}
          disabled={test.isPending}
          className="mt-[var(--space-3)] rounded-[var(--radius-md)] border border-border bg-surface px-[var(--space-3)] py-[var(--space-2)] text-sm font-medium hover:bg-surface-raised disabled:opacity-60"
        >
          {test.isPending ? "Testing…" : "Test provider"}
        </button>
        {test.data ? (
          <p role="status" className="mt-[var(--space-3)] text-sm">
            {test.data.ok
              ? `Provider responded in ${test.data.latency_ms} ms.`
              : `Provider did not respond: ${test.data.detail_code ?? "unknown"}.`}
          </p>
        ) : null}
      </div>

      <div className={PANEL}>
        <h3 className="mb-[var(--space-3)] text-base font-semibold tracking-tight">
          Coverage
        </h3>
      {/*
        Four states, not two. "No provider is enabled" is a claim about
        privacy, so it may only be rendered when the server has actually said
        so. Collapsing loading and error into it told a user that nothing was
        being transmitted while the request that would have revealed otherwise
        was still in flight.
      */}
      {status.isPending ? (
        <p role="status" className="text-sm text-text-muted">
          Checking coverage…
        </p>
      ) : status.isError ? (
        <p role="status" className="text-sm text-text-muted">
          Coverage could not be read, so this page cannot say whether a
          provider is enabled. Retry, or check{" "}
          <code className="rounded-[var(--radius-sm)] bg-surface-sunken px-[var(--space-1)]">
            codeatlas settings {repositoryId}
          </code>
          .
        </p>
      ) : status.data && status.data.coverage !== null ? (
        <p className="text-sm">
          {Math.round(status.data.coverage * 100)}% of this snapshot is
          embedded ({status.data.embedded_count} of {status.data.total_count}
          {status.data.failed_count ? `, ${status.data.failed_count} failed` : ""}
          ).
        </p>
      ) : (
        <p className="text-sm text-text-muted">
          No provider is enabled, so there is nothing to cover. This is not a
          degraded state.
        </p>
      )}
      </div>
    </section>
  );
}
