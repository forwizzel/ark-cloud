import { useEffect } from "react";

const guards = new Map<symbol, string>();
let approvedNavigation = false;
let subscribers = 0;
const indexKey = "arkNavigationIndex";

function confirmNavigation() {
  if (approvedNavigation) {
    approvedNavigation = false;
    return true;
  }
  return !guards.size || window.confirm([...guards.values()].join("\n\n"));
}

/** Guard history transitions before the application unmounts a dirty editor. */
export function useNavigationGuard() {
  useEffect(() => {
    subscribers += 1;
    if (subscribers > 1)
      return () => {
        subscribers -= 1;
      };
    let currentIndex = Number(window.history.state?.[indexKey] ?? 0);
    let currentUrl = window.location.href;
    let restoring = false;
    let approvedHash = "";
    let blockedHash = "";
    window.history.replaceState(
      { ...window.history.state, [indexKey]: currentIndex },
      "",
    );
    const stop = (event: Event) => event.stopImmediatePropagation();
    const onPopState = (event: PopStateEvent) => {
      const nextIndex = event.state?.[indexKey];
      if (restoring) {
        restoring = false;
        blockedHash = window.location.href;
        stop(event);
        return;
      }
      // New fragment entries have no state until hashchange assigns an index.
      if (typeof nextIndex !== "number") return;
      if (nextIndex === currentIndex) return;
      if (!confirmNavigation()) {
        restoring = true;
        window.history.go(currentIndex - nextIndex);
        stop(event);
        return;
      }
      currentIndex = nextIndex;
      currentUrl = window.location.href;
      approvedHash = currentUrl;
    };
    const onHashChange = (event: HashChangeEvent) => {
      if (restoring || blockedHash === window.location.href) {
        blockedHash = "";
        stop(event);
        return;
      }
      if (approvedHash === window.location.href) {
        approvedHash = "";
        return;
      }
      if (!confirmNavigation()) {
        if (window.history.state?.[indexKey] === undefined) {
          restoring = true;
          window.history.back();
        } else {
          window.history.replaceState(
            window.history.state,
            "",
            event.oldURL || currentUrl,
          );
        }
        stop(event);
        return;
      }
      currentIndex += 1;
      currentUrl = window.location.href;
      window.history.replaceState(
        { ...window.history.state, [indexKey]: currentIndex },
        "",
      );
    };
    window.addEventListener("popstate", onPopState, true);
    window.addEventListener("hashchange", onHashChange, true);
    return () => {
      subscribers -= 1;
      window.removeEventListener("popstate", onPopState, true);
      window.removeEventListener("hashchange", onHashChange, true);
    };
  }, []);
}

export default function useUnsavedChanges(
  dirty: boolean,
  leaveMessage = "Discard your unsaved changes and leave this page?",
) {
  useEffect(() => {
    if (!dirty) return;
    const id = Symbol("navigation guard");
    guards.set(id, leaveMessage);
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const guardNavigation = (event: Event) => {
      if (!(event.target instanceof Element)) return;
      const control = event.target.closest<HTMLElement>(
        "a[href], [role=tab], [data-discard-changes]",
      );
      if (!control) return;
      if (event instanceof MouseEvent && control instanceof HTMLSelectElement)
        return;
      if (
        event instanceof MouseEvent &&
        (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)
      )
        return;
      if (control instanceof HTMLAnchorElement) {
        if (control.target === "_blank" || control.hasAttribute("download"))
          return;
        if (
          control.hash === "#main-content" ||
          control.href === window.location.href
        )
          return;
      }
      if (event instanceof KeyboardEvent) {
        if (
          control.getAttribute("role") !== "tab" ||
          !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
        )
          return;
      } else if (control.getAttribute("aria-selected") === "true") return;
      if (!window.confirm(leaveMessage)) {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (control instanceof HTMLSelectElement)
          control.value = control.dataset.currentValue ?? "";
      } else if (!(control instanceof HTMLSelectElement)) {
        approvedNavigation = true;
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", guardNavigation, true);
    document.addEventListener("keydown", guardNavigation, true);
    document.addEventListener("change", guardNavigation, true);
    return () => {
      guards.delete(id);
      approvedNavigation = false;
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", guardNavigation, true);
      document.removeEventListener("keydown", guardNavigation, true);
      document.removeEventListener("change", guardNavigation, true);
    };
  }, [dirty, leaveMessage]);
  return () => !dirty || window.confirm(leaveMessage);
}
