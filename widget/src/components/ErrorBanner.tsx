interface ErrorBannerProps {
  message: string;
}

export function ErrorBanner({ message }: ErrorBannerProps) {
  return (
    <div class="va-error-banner" role="alert">
      {message}
    </div>
  );
}
