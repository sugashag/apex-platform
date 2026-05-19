import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
}

export function ErrorState({ title = "Something went wrong", message, onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-danger/40 bg-danger-muted/50 px-6 py-10 text-center">
      <AlertTriangle className="mb-2 h-5 w-5 text-danger" aria-hidden />
      <h3 className="text-sm font-semibold text-danger">{title}</h3>
      {message ? <p className="mt-1 max-w-md text-sm text-slate-700">{message}</p> : null}
      {onRetry ? (
        <Button size="sm" variant="outline" className="mt-4" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
