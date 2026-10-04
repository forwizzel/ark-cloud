/** Reveal the selected destination without leaving a half-cut label at the start. */
export function revealDestination(strip: HTMLElement, active: HTMLElement) {
  const end = active.getBoundingClientRect().right;
  let start = active.getBoundingClientRect().left;
  const items = Array.from(strip.children).filter(
    (item): item is HTMLElement => item instanceof HTMLElement,
  );
  for (const item of items.slice(0, items.indexOf(active)).reverse()) {
    if (end - item.getBoundingClientRect().left > strip.clientWidth - 8) break;
    start = item.getBoundingClientRect().left;
  }
  strip.scrollTo?.({
    left: Math.max(
      0,
      strip.scrollLeft + start - strip.getBoundingClientRect().left - 5,
    ),
    behavior: "instant",
  });
}
