import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import AdministrationTabs from "./AdministrationTabs";

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

test("deep links select their parent tab, including the legacy Users route", () => {
  const { rerender } = render(
    <AdministrationTabs route="#administration/storage/settings" />,
  );
  expect(screen.getByRole("tab", { name: "Storage" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  rerender(<AdministrationTabs route="#administration-users" />);
  expect(screen.getByRole("tab", { name: "Users" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute(
    "tabindex",
    "-1",
  );
  rerender(<AdministrationTabs route="#administration/tailscale" />);
  expect(screen.getByRole("tab", { name: "Tailscale" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

test("tabs support arrow wrapping, Home, End, and click navigation", async () => {
  render(<AdministrationTabs route="#administration" />);
  const overview = screen.getByRole("tab", { name: "Overview" });
  const users = screen.getByRole("tab", { name: "Users" });
  fireEvent.keyDown(overview, { key: "ArrowLeft" });
  expect(users).toHaveFocus();
  expect(window.location.hash).toBe("#administration/users");
  fireEvent.keyDown(users, { key: "ArrowRight" });
  expect(overview).toHaveFocus();
  fireEvent.keyDown(overview, { key: "End" });
  expect(users).toHaveFocus();
  fireEvent.keyDown(users, { key: "Home" });
  expect(overview).toHaveFocus();
  fireEvent.click(screen.getByRole("tab", { name: "Storage" }));
  await waitFor(() =>
    expect(window.location.hash).toBe("#administration/storage"),
  );
});

test("route tabs retain native links for opening another tab", () => {
  render(<AdministrationTabs route="#administration" />);
  const storage = screen.getByRole("tab", { name: "Storage" });
  expect(storage.tagName).toBe("A");
  expect(storage).toHaveAttribute("href", "#administration/storage");
});
