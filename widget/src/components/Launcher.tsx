import { ChatIcon, CloseIcon } from "../icons";

interface LauncherProps {
  open: boolean;
  position: "left" | "right";
  agentName: string;
  onToggle: () => void;
}

export function Launcher({ open, position, agentName, onToggle }: LauncherProps) {
  return (
    <button
      type="button"
      class={`va-launcher va-pos-${position}`}
      onClick={onToggle}
      aria-label={open ? "Close chat" : `Chat with ${agentName}`}
      aria-expanded={open}
    >
      {open ? <CloseIcon /> : <ChatIcon />}
    </button>
  );
}
