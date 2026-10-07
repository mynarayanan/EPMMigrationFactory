import { render, screen } from "@testing-library/react";
import { GateRail, Pill, ScoreBar } from "./components/ui";

test("GateRail exposes each phase and its state to assistive tech", () => {
  render(<GateRail phases={[{ key: "a", label: "Discovery", state: "DONE" }, { key: "b", label: "Readiness gate", state: "FAILED" }, { key: "c", label: "Plan", state: "PENDING" }]} />);
  const items = screen.getAllByRole("listitem");
  expect(items).toHaveLength(3);
  expect(items[0]).toHaveClass("DONE"); expect(items[1]).toHaveClass("FAILED");
  expect(screen.getByText(/readiness gate/i).textContent).toMatch(/failed/);
});

test("ScoreBar colours by threshold and is a labelled meter", () => {
  const { rerender } = render(<ScoreBar score={95} />);
  expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "95");
  expect(screen.getByRole("meter").querySelector("i")).not.toHaveClass("low");
  rerender(<ScoreBar score={60} />);
  expect(screen.getByRole("meter").querySelector("i")).toHaveClass("low");
});

test("Pill humanises state names", () => {
  render(<Pill value="AWAITING_APPROVAL" />);
  expect(screen.getByText("AWAITING APPROVAL")).toHaveClass("AWAITING_APPROVAL");
});
