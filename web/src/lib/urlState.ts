/**
 * The filters and sort order live in the query string, so a DDM officer can
 * send a colleague the exact view they are looking at. The filter row, the
 * map and the table all read that one state, so they always agree.
 *
 * The URL is read as an external store: the server snapshot is empty, so the
 * prerendered HTML is the default view, and the client switches to the URL's
 * view on hydration without a mismatch. For client components only.
 */

import { useMemo, useSyncExternalStore } from "react";

import { parseState, serialiseState, type TableState } from "./table";

const URL_EVENT = "jamunarekha:urlchange";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(URL_EVENT, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(URL_EVENT, onChange);
  };
}

const readSearch = () => window.location.search;
const readServerSearch = () => "";

export function useTableState(): TableState {
  const search = useSyncExternalStore(subscribe, readSearch, readServerSearch);
  return useMemo(() => parseState(search), [search]);
}

export function writeState(state: TableState): void {
  const query = serialiseState(state);
  window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
  window.dispatchEvent(new Event(URL_EVENT));
}
