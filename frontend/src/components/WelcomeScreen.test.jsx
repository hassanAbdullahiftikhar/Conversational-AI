import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WelcomeScreen from "./WelcomeScreen";

describe("WelcomeScreen", () => {
  it("invokes quick prompts when connected", async () => {
    const user = userEvent.setup();
    const onQuickPrompt = vi.fn();

    render(<WelcomeScreen onQuickPrompt={onQuickPrompt} isConnected={true} />);

    await user.click(screen.getByRole("button", { name: /track my order/i }));

    expect(onQuickPrompt).toHaveBeenCalledWith("I want to track my order.");
  });

  it("disables quick prompts when the channel is offline", () => {
    render(<WelcomeScreen onQuickPrompt={vi.fn()} isConnected={false} />);

    expect(screen.getByRole("button", { name: /track my order/i })).toBeDisabled();
    expect(screen.getByText(/reconnecting/i)).toBeInTheDocument();
  });
});