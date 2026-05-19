import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { Building2 } from "lucide-react";

export default function CompaniesPage() {
  return (
    <div>
      <PageHeader title="Companies" description="Coming soon." />
      <div className="p-4 md:p-6">
        <EmptyState
          icon={Building2}
          title="Companies — coming soon"
          description="The companies view is in the works. Contacts and deals already carry company context today."
        />
      </div>
    </div>
  );
}
