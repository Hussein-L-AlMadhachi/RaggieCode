// Minimal toast store: a reactive list of transient notifications shown by
// ToastHost.svelte. Not blocking, not focus-stealing.

export type ToastKind = 'info' | 'success' | 'error';

export type Toast = {
  id: number;
  message: string;
  kind: ToastKind;
};

export const toasts = $state<Toast[]>([]);

let nextId = 0;

// Cap so a burst of errors can't bury the composer; oldest drops first.
const MAX_TOASTS = 4;
const DISMISS_MS = 4000;
const DISMISS_ERROR_MS = 6000;

/** Push a toast. Errors stay a bit longer. Returns the toast id. */
export function toast(message: string, kind: ToastKind = 'info'): number {
  const id = ++nextId;
  const timeout = kind === 'error' ? DISMISS_ERROR_MS : DISMISS_MS;
  toasts.push({ id, message, kind });
  if (toasts.length > MAX_TOASTS) toasts.shift();
  setTimeout(() => dismiss(id), timeout);
  return id;
}

/** Remove a toast by id (close button, click, or auto-dismiss). */
export function dismiss(id: number): void {
  const idx = toasts.findIndex((t) => t.id === id);
  if (idx >= 0) toasts.splice(idx, 1);
}
