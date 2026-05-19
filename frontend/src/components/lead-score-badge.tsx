import { Badge } from "@/components/ui/badge";
import { leadScoreBucket } from "@/lib/utils";

export function LeadScoreBadge({ score }: { score: number }) {
  const bucket = leadScoreBucket(score);
  const variant = bucket === "low" ? "danger" : bucket === "med" ? "warning" : "success";
  return (
    <Badge variant={variant} aria-label={`Lead score ${score}`}>
      {score}
    </Badge>
  );
}
