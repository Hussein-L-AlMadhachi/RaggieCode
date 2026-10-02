/**
 * Global tracking of in-flight JSON-RPC requests (issued via `rpc()` in api.ts).
 *
 * Components can react to `rpcBusy` or query a specific request id with
 * `isBusy(id)` / `busyMethod(id)` (useful when a caller holds its own id,
 * e.g. captured from an rpc() wrapper).
 */

export type InFlightRpc = { method: string; startedAt: number };

// Reactive map of in-flight requests, keyed by JSON-RPC id.
const inFlight = $state<Record<number, InFlightRpc>>({});

// Ids with in-flight requests. Reading this inside a template/effect stays
// reactive because inFlight is $state.
export function busyIds(): number[] {
  return Object.keys(inFlight).map(Number);
}

// Start tracking a request. Called by api.ts only.
export function begin(id: number, method: string): void {
  inFlight[id] = { method, startedAt: Date.now() };
}

// Stop tracking a request (on response or error). Called by api.ts only.
export function end(id: number): void {
  delete inFlight[id];
}

export function isBusy(id: number): boolean {
  return inFlight[id] !== undefined;
}

export function busyMethod(id: number): string | undefined {
  return inFlight[id]?.method;
}

export function busyEntry(id: number): InFlightRpc | undefined {
  return inFlight[id];
}
