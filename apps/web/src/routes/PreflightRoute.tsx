import { useNavigate } from "react-router-dom";

import { useActiveRepository } from "../app/context";
import { PreflightLauncher } from "../features/change-analysis/PreflightLauncher";
import { rememberAnalysis } from "../features/change-analysis/lastAnalysis";

/**
 * The preflight launcher.
 *
 * Running an analysis navigates to its id, so the persisted report — not the
 * component's memory — is what a reload or a shared link resolves to. The id is
 * also remembered per repository, because the URL was the only thing holding it:
 * leaving the screen and coming back through the sidebar landed here, on an
 * empty launcher, which read as the analysis having been thrown away.
 */
export function PreflightRoute() {
  const { repositoryId } = useActiveRepository();
  const navigate = useNavigate();

  return (
    <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
      <PreflightLauncher
        repositoryId={repositoryId}
        onAnalysed={(analysisId) => {
          rememberAnalysis(repositoryId, analysisId);
          navigate(`/preflight/${analysisId}`);
        }}
      />
    </div>
  );
}
