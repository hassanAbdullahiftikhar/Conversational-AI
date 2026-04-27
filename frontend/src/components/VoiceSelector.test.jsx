import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VoiceSelector from "./VoiceSelector";

describe("VoiceSelector", () => {
  it("invokes callbacks for voice, speed, and speech controls", async () => {
    const user = userEvent.setup();
    const onVoiceChange = vi.fn();
    const onSpeedChange = vi.fn();
    const onSpeechToggle = vi.fn();

    render(
      <VoiceSelector
        currentVoice="af_bella"
        currentSpeed={1.5}
        speechEnabled={true}
        onVoiceChange={onVoiceChange}
        onSpeedChange={onSpeedChange}
        onSpeechToggle={onSpeechToggle}
        disabled={false}
      />
    );

    await user.click(screen.getByRole("button", { name: /^sarah$/i }));
    await user.selectOptions(screen.getByLabelText(/voice speed/i), "2");
    await user.click(screen.getByRole("button", { name: /voice on/i }));

    expect(onVoiceChange).toHaveBeenCalledWith("af_sarah");
    expect(onSpeedChange).toHaveBeenCalledWith(2);
    expect(onSpeechToggle).toHaveBeenCalledTimes(1);
  });

  it("disables controls when the panel is locked", () => {
    render(
      <VoiceSelector
        currentVoice="af_bella"
        currentSpeed={1}
        speechEnabled={true}
        onVoiceChange={vi.fn()}
        onSpeedChange={vi.fn()}
        onSpeechToggle={vi.fn()}
        disabled={true}
      />
    );

    expect(screen.getByRole("button", { name: /^bella$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /voice on/i })).toBeDisabled();
    expect(screen.getByLabelText(/voice speed/i)).toBeDisabled();
  });
});