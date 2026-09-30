import Link from "next/link";
import { EmptyState } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-lg py-12">
      <EmptyState
        icon="search"
        title="Page not found"
        description="The page you're looking for doesn't exist or may have moved."
        action={
          <Link href="/" className="btn-primary">
            Go home
          </Link>
        }
      />
    </div>
  );
}
