import { fireEvent, render, screen } from "@testing-library/react";
import { SourceForm } from "../source-form";

describe("SourceForm", () => {
  it("renders core controls", () => {
    render(<SourceForm onAccepted={() => undefined} />);
    expect(screen.getByRole("heading", { name: /Video Pipeline/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Input Mode")).toBeInTheDocument();
    expect(screen.getByLabelText("Video URL")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run Analysis \+ Planner/i })).toBeInTheDocument();
  });

  it("switches from URL to upload mode", () => {
    render(<SourceForm onAccepted={() => undefined} />);
    fireEvent.change(screen.getByLabelText("Input Mode"), { target: { value: "upload" } });
    expect(screen.getByLabelText("Video File")).toBeInTheDocument();
  });
});
