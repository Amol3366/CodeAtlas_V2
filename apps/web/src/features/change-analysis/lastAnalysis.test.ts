import { beforeEach, describe, expect, it } from "vitest";

import {
  forgetAnalysis,
  lastAnalysisId,
  rememberAnalysis,
} from "./lastAnalysis";

describe("the last analysis pointer", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("has nothing to offer before a preflight has run", () => {
    expect(lastAnalysisId("repo_1")).toBeNull();
  });

  it("resolves the analysis last run for that repository", () => {
    rememberAnalysis("repo_1", "an_1");

    expect(lastAnalysisId("repo_1")).toBe("an_1");
  });

  it("keeps each repository's analysis apart", () => {
    rememberAnalysis("repo_1", "an_1");
    rememberAnalysis("repo_2", "an_2");

    expect(lastAnalysisId("repo_1")).toBe("an_1");
    expect(lastAnalysisId("repo_2")).toBe("an_2");
  });

  it("replaces the pointer when the same repository is analysed again", () => {
    rememberAnalysis("repo_1", "an_1");
    rememberAnalysis("repo_1", "an_2");

    expect(lastAnalysisId("repo_1")).toBe("an_2");
  });

  it("offers nothing when no repository is selected", () => {
    rememberAnalysis(null, "an_1");

    expect(lastAnalysisId(null)).toBeNull();
  });

  it("forgets a pointer whose analysis no longer resolves", () => {
    rememberAnalysis("repo_1", "an_1");
    rememberAnalysis("repo_2", "an_2");

    forgetAnalysis("repo_1");

    expect(lastAnalysisId("repo_1")).toBeNull();
    expect(lastAnalysisId("repo_2")).toBe("an_2");
  });

  it("survives storage holding something that is not a pointer map", () => {
    window.localStorage.setItem("codeatlas.last-analysis", "not json");

    expect(lastAnalysisId("repo_1")).toBeNull();
    expect(() => rememberAnalysis("repo_1", "an_1")).not.toThrow();
    expect(lastAnalysisId("repo_1")).toBe("an_1");
  });
});
