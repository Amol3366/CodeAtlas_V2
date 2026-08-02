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
    <section aria-labelledby="semantic-settings-heading">
      <h2 id="semantic-settings-heading">Semantic search</h2>
      <p>
        Semantic search is optional. CodeAtlas answers with exact, lexical,
        graph, and Git retrieval whether or not it is enabled.
      </p>

      <form onSubmit={save}>
        <fieldset>
          <legend>Embedding provider</legend>
          {models.data?.models.map((model) => (
            <label key={model.provider} htmlFor={`provider-${model.provider}`}>
              <input
                id={`provider-${model.provider}`}
                type="radio"
                name="embedding-provider"
                value={model.provider}
                checked={provider === model.provider}
                disabled={!model.available}
                onChange={() => setProvider(model.provider)}
              />
              <span>{PROVIDER_LABELS[model.provider] ?? model.provider}</span>
              {/* Words, not colour. Section 14.4 forbids colour alone for a
                  status this consequential. */}
              <span>
                {model.transmits_off_machine
                  ? "⚠ Sends repository content off this machine"
                  : "Stays on this machine"}
              </span>
              {!model.available && model.requires !== null ? (
                <span>Unavailable — requires {model.requires}</span>
              ) : null}
            </label>
          ))}
        </fieldset>

        <fieldset>
          <legend>Answer provider</legend>
          <p>
            CodeAtlas always finds and cites the evidence itself. An answer
            provider adds a written explanation on top of it; the citations and
            their confidence never change.
          </p>
          {models.data?.answer_models?.map((model) => (
            <label
              key={model.provider}
              htmlFor={`answer-provider-${model.provider}`}
            >
              <input
                id={`answer-provider-${model.provider}`}
                type="radio"
                name="answer-provider"
                value={model.provider}
                checked={answerProvider === model.provider}
                onChange={() => setAnswerProvider(model.provider)}
              />
              <span>
                {ANSWER_PROVIDER_LABELS[model.provider] ?? model.provider}
              </span>
              {/* Words, not colour — the same rule the embedding options obey. */}
              <span>
                {model.transmits_off_machine
                  ? "⚠ Sends repository content off this machine"
                  : "Stays on this machine"}
              </span>
              {model.requires !== null ? (
                <span>Requires {model.requires}</span>
              ) : null}
            </label>
          ))}
        </fieldset>

        {answerProvider !== "none" ? (
          <div>
            <label htmlFor="answer-model">Answer model</label>
            <input
              id="answer-model"
              type="text"
              value={answerModel}
              placeholder={chosenAnswer?.model_id ?? ""}
              onChange={(event) => setAnswerModel(event.target.value)}
              aria-describedby="answer-model-help"
            />
            <p id="answer-model-help">
              Leave blank to use {chosenAnswer?.model_id ?? "the default"}. A
              larger model reasons better across files, needs more memory, and
              answers more slowly. A local model must already be installed —
              for example <code>ollama pull llama3.1:8b</code>.
            </p>
          </div>
        ) : null}

        {transmits ? (
          <div>
            <label htmlFor="monthly-budget">
              Monthly token budget (required)
            </label>
            <input
              id="monthly-budget"
              type="number"
              min={0}
              value={monthlyBudget}
              onChange={(event) => setMonthlyBudget(event.target.value)}
              aria-describedby="monthly-budget-help"
            />
            <p id="monthly-budget-help">
              A provider that sends content off this machine cannot be enabled
              without a spending bound.
            </p>
          </div>
        ) : null}

        <button type="submit" disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save"}
        </button>
      </form>

      {update.isError ? (
        <p role="alert">{(update.error as Error).message}</p>
      ) : null}
      {update.isSuccess ? <p role="status">Settings saved.</p> : null}

      <h3>Connection</h3>
      <button
        type="button"
        onClick={() => test.mutate()}
        disabled={test.isPending}
      >
        {test.isPending ? "Testing…" : "Test provider"}
      </button>
      {test.data ? (
        <p role="status">
          {test.data.ok
            ? `Provider responded in ${test.data.latency_ms} ms.`
            : `Provider did not respond: ${test.data.detail_code ?? "unknown"}.`}
        </p>
      ) : null}

      <h3>Coverage</h3>
      {/*
        Four states, not two. "No provider is enabled" is a claim about
        privacy, so it may only be rendered when the server has actually said
        so. Collapsing loading and error into it told a user that nothing was
        being transmitted while the request that would have revealed otherwise
        was still in flight.
      */}
      {status.isPending ? (
        <p role="status">Checking coverage…</p>
      ) : status.isError ? (
        <p role="status">
          Coverage could not be read, so this page cannot say whether a
          provider is enabled. Retry, or check{" "}
          <code>codeatlas settings {repositoryId}</code>.
        </p>
      ) : status.data && status.data.coverage !== null ? (
        <p>
          {Math.round(status.data.coverage * 100)}% of this snapshot is
          embedded ({status.data.embedded_count} of {status.data.total_count}
          {status.data.failed_count ? `, ${status.data.failed_count} failed` : ""}
          ).
        </p>
      ) : (
        <p>
          No provider is enabled, so there is nothing to cover. This is not a
          degraded state.
        </p>
      )}
    </section>
  );
}
