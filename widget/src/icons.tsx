// Minimal inline SVGs — avoids pulling in an icon font/library for three shapes.

export function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path
        d="M4 4h16v12H7.5L4 19.5V4z"
        stroke="currentColor"
        stroke-width="2"
        stroke-linejoin="round"
        fill="none"
      />
    </svg>
  );
}

export function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path
        d="M6 6l12 12M18 6L6 18"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
      />
    </svg>
  );
}

export function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path
        d="M4 12l16-8-6 8 6 8-16-8z"
        fill="currentColor"
      />
    </svg>
  );
}

export function SpinnerIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" class="va-spin">
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        stroke-width="2.5"
        stroke-linecap="round"
        stroke-dasharray="42"
        stroke-dashoffset="14"
        fill="none"
      />
    </svg>
  );
}

export function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" stroke="currentColor" stroke-width="2" />
      <path
        d="M5 11a7 7 0 0 0 14 0M12 18v3"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
      />
    </svg>
  );
}
