import { useTheme } from "../../app/theme";

/**
 * Theme selection.
 *
 * A select rather than an icon button: three states (system, light, dark)
 * cannot be conveyed by one toggle, and "system" is the honest default because
 * it is what the user already chose at the OS level.
 */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <>
      <label htmlFor="theme" className="sr-only">
        Theme
      </label>
      <select
        id="theme"
        value={theme}
        onChange={(changed) =>
          setTheme(changed.target.value as "light" | "dark" | "system")
        }
        className="rounded-[var(--radius-sm)] border border-border bg-surface px-[var(--space-1)] py-[2px] text-xs"
      >
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </>
  );
}
