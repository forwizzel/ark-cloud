import { useEffect } from "react";

export default function useUnsavedChanges(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
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
      if (
        !window.confirm("Discard your unsaved changes and leave this page?")
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (control instanceof HTMLSelectElement)
          control.value = control.dataset.currentValue ?? "";
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", guardNavigation, true);
    document.addEventListener("keydown", guardNavigation, true);
    document.addEventListener("change", guardNavigation, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", guardNavigation, true);
      document.removeEventListener("keydown", guardNavigation, true);
      document.removeEventListener("change", guardNavigation, true);
    };
  }, [dirty]);
  return () => !dirty || window.confirm("Discard your unsaved changes?");
}
