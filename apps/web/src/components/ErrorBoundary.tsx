import { Component } from "react";
import type { ReactNode } from "react";

interface Props {
  readonly children: ReactNode;
}

interface State {
  readonly failed: boolean;
}

/**
 * Keeps one broken panel from blanking the application.
 *
 * The message is deliberately generic: an exception can carry a path or a
 * fragment of repository content, and neither belongs on screen.
 */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  override componentDidCatch(): void {
    // Intentionally not logged: an exception can carry a path or a fragment of
    // repository content, and neither belongs in a console or a log.
  }

  override render(): ReactNode {
    if (this.state.failed) {
      return (
        <div role="alert" className="p-6 text-text">
          <h2 className="text-lg font-semibold">Something went wrong</h2>
          <p className="mt-2 text-text-muted">
            This part of the page could not be displayed. Reloading usually
            resolves it.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
