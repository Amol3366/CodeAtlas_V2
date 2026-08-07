import { Link, useParams } from "react-router-dom";

import { ErrorNotice } from "../components/ErrorNotice";
import { Skeleton } from "../components/Skeleton";
import { AnalysisSummary } from "../features/change-analysis/AnalysisSummary";
import { ChangedSymbols } from "../features/change-analysis/ChangedSymbols";
import { FindingsList } from "../features/change-analysis/FindingsList";
import { ImpactList } from "../features/change-analysis/ImpactList";
import { ReportNotes } from "../features/change-analysis/ReportNotes";
import { TestGaps } from "../features/change-analysis/TestGaps";
import { evidenceById, useAnalysis } from "../features/change-analysis/useAnalysis";

/**
 * One persisted change analysis, loaded by id.
 *
 * The id is in the URL because a stored analysis is an audit record: re-opening
 * it never re-analyzes, and running it again could quietly produce a different
 * answer to the same question. A screen that lost the record on reload would
 * contradict a property the product claims.
 *
 * Read verdict-first — a developer whose change is fine reads the header and
 * stops.
 */
export function PreflightAnalysisRoute() {
  const { analysisId } = useParams();
  const analysis = useAnalysis(analysisId);

  if (analysis.isPending) {
    return (
      <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
        <Skeleton label="Loading the analysis" className="h-24" />
      </div>
    );
  }

  if (analysis.isError) {
    return (
      <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
        <p className="text-sm">That analysis was not found.</p>
        <ErrorNotice error={analysis.error} />
        <p className="mt-[var(--space-3)] text-sm">
          <Link to="/preflight" className="underline">
            Run a preflight
          </Link>
        </p>
      </div>
    );
  }

  const report = analysis.data;
  // Built once and shared: both findings and gaps resolve citations through it.
  const evidence = evidenceById(report);

  return (
    <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
      <AnalysisSummary report={report} />

      <section aria-labelledby="findings" className="mt-[var(--space-6)]">
        <h2 id="findings" className="text-sm font-semibold">
          Findings
        </h2>
        <FindingsList
          findings={report.findings ?? []}
          evidence={evidence}
        />
      </section>

      <section aria-labelledby="what-changed" className="mt-[var(--space-6)]">
        <h2 id="what-changed" className="text-sm font-semibold">
          What changed
        </h2>
        <div className="mt-[var(--space-2)]">
          <ChangedSymbols
            symbols={report.changed_symbols ?? []}
            files={report.changed_files ?? []}
          />
        </div>
      </section>

      {(report.impact_edges ?? []).length > 0 ? (
        <section aria-labelledby="what-it-reaches" className="mt-[var(--space-6)]">
          <h2 id="what-it-reaches" className="text-sm font-semibold">
            What it reaches
          </h2>
          <div className="mt-[var(--space-2)]">
            <ImpactList edges={report.impact_edges ?? []} />
          </div>
        </section>
      ) : null}

      <TestGaps
        gaps={report.test_gaps ?? []}
        reasons={report.test_gap_reasons ?? []}
        evidence={evidence}
      />

      <ReportNotes
        warnings={report.warnings ?? []}
        limitations={report.limitations ?? []}
      />
    </div>
  );
}
