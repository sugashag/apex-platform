import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { Phone } from "lucide-react";

export default function CallsPage() {
  return (
    <div>
      <PageHeader title="Calls" description="Coming soon." />
      <div className="p-4 md:p-6">
        <EmptyState
          icon={Phone}
          title="Calls — coming soon"
          description="The call console is in the works. Twilio voice is already wired up on the backend."
        />
      </div>
    </div>
  );
}
