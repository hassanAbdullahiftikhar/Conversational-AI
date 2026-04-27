import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SessionControls from "./SessionControls";

describe("SessionControls", () => {
  it("toggles the debug state and triggers session actions", async () => {
    const user = userEvent.setup();
    const onNewSession = vi.fn();
    const onReset = vi.fn();
    const onToggleDiagnostics = vi.fn();

    render(
      <SessionControls
        onNewSession={onNewSession}
        onReset={onReset}
        isConnected={true}
        diagnosticsEnabled={false}
        onToggleDiagnostics={onToggleDiagnostics}
      />
    );

    await user.click(screen.getByRole("button", { name: /new chat/i }));
    await user.click(screen.getByRole("button", { name: /clear/i }));
    await user.click(screen.getByRole("button", { name: /debug/i }));

    expect(onNewSession).toHaveBeenCalledTimes(1);
    expect(onReset).toHaveBeenCalledTimes(1);
    expect(onToggleDiagnostics).toHaveBeenCalledTimes(1);
  });

  it("disables controls when disconnected", () => {
    render(
      <SessionControls
        onNewSession={vi.fn()}
        onReset={vi.fn()}
        isConnected={false}
        diagnosticsEnabled={true}
        onToggleDiagnostics={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: /new chat/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /clear/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /debug on/i })).toBeDisabled();
  });
});