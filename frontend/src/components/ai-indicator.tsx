import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

export function AiBadge({ className, label = "AI" }: { className?: string; label?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full bg-ai-muted px-2 py-0.5 text-xs font-medium text-ai",
        className
      )}
    >
      <Sparkles className="h-3 w-3" aria-hidden />
      {label}
    </span>
  );
}
