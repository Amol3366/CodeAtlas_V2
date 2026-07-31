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

export function SemanticSettings({ repositoryId }: Props) {
  const settings = useSettings(repositoryId);
  const models = useModels();
  const status = useSemanticStatus(repositoryId);
  const update = useUpdateSettings(repositoryId);
  const test = useTestProvider(repositoryId);

  const [provider, setProvider] = useState<string>("none");
  const [monthlyBudget, setMonthlyBudget] = useState<string>("");

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
    }
  }, [settings.data]);

  const chosen = models.data?.models.find((item) => item.provider === provider);
  const transmits = chosen?.transmits_off_machine ?? false;

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
    update.mutate({
      embedding_provider: provider,
      monthly_token_budget: parsed,
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
      {status.data && status.data.coverage !== null ? (
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
