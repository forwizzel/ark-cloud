/** Reveal the selected destination without leaving a half-cut label at the start. */
export function revealDestination(strip: HTMLElement, active: HTMLElement) {
  const activeRect = active.getBoundingClientRect();
  const stripRect = strip.getBoundingClientRect();
  const end = activeRect.right;
  let start = activeRect.left;
  const items = Array.from(strip.children).filter(
    (item): item is HTMLElement => item instanceof HTMLElement,
  );
  for (const item of items.slice(0, items.indexOf(active)).reverse()) {
    const left = item.getBoundingClientRect().left;
    if (end - left > strip.clientWidth - 8) break;
    start = left;
  }
  strip.scrollTo?.({
    left: Math.max(0, strip.scrollLeft + start - stripRect.left - 5),
    behavior: "instant",
  });
}
