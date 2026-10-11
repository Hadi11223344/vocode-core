import Link from 'next/link';
import { Compass } from 'lucide-react';

export default function DashboardNotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 p-6">
      <div className="w-14 h-14 rounded-2xl bg-brand-500/10 flex items-center justify-center">
        <Compass size={28} className="text-brand-400" />
      </div>
      <div className="text-center space-y-1.5">
        <h2 className="text-lg font-semibold">Page Not Found</h2>
        <p className="text-sm text-[var(--text-muted)] max-w-md">
          The page you&apos;re looking for doesn&apos;t exist or may have been moved.
        </p>
      </div>
      <Link href="/dashboard" className="btn-primary">
        Back to Dashboard
      </Link>
    </div>
  );
}
