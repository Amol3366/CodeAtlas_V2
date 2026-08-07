import { useNavigate } from "react-router-dom";

import { useActiveRepository } from "../app/context";
import { PreflightLauncher } from "../features/change-analysis/PreflightLauncher";

/**
 * The preflight launcher.
 *
 * Running an analysis navigates to its id, so the persisted report — not the
 * component's memory — is what a reload or a shared link resolves to.
 */
export function PreflightRoute() {
  const { repositoryId } = useActiveRepository();
  const navigate = useNavigate();

  return (
    <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
      <PreflightLauncher
        repositoryId={repositoryId}
        onAnalysed={(analysisId) => navigate(`/preflight/${analysisId}`)}
      />
    </div>
  );
}
