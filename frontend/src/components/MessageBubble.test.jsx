import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MessageBubble from "./MessageBubble";

describe("MessageBubble", () => {
  it("copies, mutes, and replays assistant messages", async () => {
    const user = userEvent.setup();
    const onToggleMute = vi.fn();
    const onReplay = vi.fn();

    render(
      <MessageBubble
        messageId="resp-1"
        role="assistant"
        content="Your order is on the way."
        isStreaming={false}
        isMuted={false}
        onToggleMute={onToggleMute}
        onReplay={onReplay}
      />
    );

    await user.click(screen.getByRole("button", { name: /copy message/i }));
    await user.click(screen.getByRole("button", { name: /mute/i }));
    await user.click(screen.getByRole("button", { name: /replay assistant response/i }));

    expect(onToggleMute).toHaveBeenCalledWith("resp-1");
    expect(onReplay).toHaveBeenCalledWith("Your order is on the way.");
  });

  it("renders user messages without assistant-only controls", () => {
    render(
      <MessageBubble
        messageId="user-1"
        role="user"
        content="Hello there"
        isStreaming={false}
        isMuted={false}
        onToggleMute={vi.fn()}
        onReplay={vi.fn()}
      />
    );

    expect(screen.getByText("Hello there")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mute/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /replay assistant response/i })).not.toBeInTheDocument();
  });
});