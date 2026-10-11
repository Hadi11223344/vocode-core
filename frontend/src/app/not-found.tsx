import Link from 'next/link';
import { Compass } from 'lucide-react';

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4 p-6 bg-[var(--bg-primary)]">
      <div className="w-14 h-14 rounded-2xl bg-brand-500/10 flex items-center justify-center">
        <Compass size={28} className="text-brand-400" />
      </div>
      <div className="text-center space-y-1.5">
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">404</h1>
        <p className="text-sm text-[var(--text-muted)] max-w-md">
          The page you&apos;re looking for doesn&apos;t exist.
        </p>
      </div>
      <Link href="/" className="btn-primary">
        Go Home
      </Link>
    </div>
  );
}
