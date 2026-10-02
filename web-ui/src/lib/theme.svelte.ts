// Light/dark theme preference. Follows the OS setting until the user
// toggles explicitly; that choice is then persisted in localStorage.
// The dataset is applied on <html> and consumed by app.css's
// html[data-theme='dark'] palette. index.html's inline bootstrap script
// sets the same value before first paint to avoid a theme flash.

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'raggie.theme';

function storedTheme(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'light' || v === 'dark' ? v : null;
  } catch {
    // Storage may be unavailable (restrictive webview, private mode).
    return null;
  }
}

function systemTheme(): Theme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export const theme = $state<{ current: Theme }>({ current: storedTheme() ?? systemTheme() });

function applyTheme() {
  document.documentElement.dataset.theme = theme.current;
}

applyTheme();

export function toggleTheme() {
  theme.current = theme.current === 'dark' ? 'light' : 'dark';
  applyTheme();
  try {
    localStorage.setItem(STORAGE_KEY, theme.current);
  } catch {
    // Not fatal: the theme just won't survive a reload.
  }
}
