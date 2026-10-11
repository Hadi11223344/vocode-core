'use client';

import Link from 'next/link';
import { FormEvent, useMemo, useState } from 'react';
import { ArrowLeft, Cloud, KeyRound, Shield, Workflow } from 'lucide-react';

const WAITLIST_URL = process.env.NEXT_PUBLIC_CLOUD_WAITLIST_URL || '';
const WAITLIST_EMAIL = process.env.NEXT_PUBLIC_CLOUD_WAITLIST_EMAIL || 'sales@voia.ai';

export default function CloudWaitlistPage() {
  const [email, setEmail] = useState('');
  const [company, setCompany] = useState('');
  const [usingOss, setUsingOss] = useState('planning');
  const [pain, setPain] = useState('telephony');
  const [submitted, setSubmitted] = useState(false);

  const mailtoHref = useMemo(() => {
    const subject = encodeURIComponent('VOIA Cloud waitlist');
    const body = encodeURIComponent(
      [
        `Email: ${email || '(add your email)'}`,
        `Company / project: ${company || '(optional)'}`,
        `Using OSS today: ${usingOss}`,
        `Main pain: ${pain}`,
        '',
        'I want managed telephony / SSO / SLA with the same graphs as self-hosted VOIA.',
      ].join('\n'),
    );
    return `mailto:${WAITLIST_EMAIL}?subject=${subject}&body=${body}`;
  }, [email, company, usingOss, pain]);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (WAITLIST_URL) {
      window.open(WAITLIST_URL, '_blank', 'noopener,noreferrer');
      setSubmitted(true);
      return;
    }
    window.location.href = mailtoHref;
    setSubmitted(true);
  };

  return (
    <div className="min-h-screen bg-[var(--bg-primary)] text-[var(--text-primary)]">
      <div className="max-w-3xl mx-auto px-4 py-10 sm:py-16">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-sm text-[var(--text-muted)] hover:text-[var(--text-primary)] mb-8"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to VOIA
        </Link>

        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-brand-500/15 flex items-center justify-center">
            <Cloud className="w-5 h-5 text-brand-400" />
          </div>
          <p className="text-sm font-medium text-brand-400">VOIA Cloud</p>
        </div>

        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight mb-3">
          Same graphs. Zero ops.
        </h1>
        <p className="text-[var(--text-secondary)] leading-relaxed mb-8 max-w-2xl">
          Self-host VOIA with your own keys today. Join the Cloud waitlist for managed
          telephony, SSO, and SLA — without rewriting your conversational flows.
        </p>

        <div className="grid sm:grid-cols-3 gap-3 mb-10">
          {[
            { icon: Workflow, label: 'Portable graphs', detail: 'Import/export the same flow JSON' },
            { icon: KeyRound, label: 'BYOK stays', detail: 'Your STT/LLM/TTS keys, even on Cloud' },
            { icon: Shield, label: 'Team-ready', detail: 'SSO, audit, and support when you need it' },
          ].map(({ icon: Icon, label, detail }) => (
            <div key={label} className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
              <Icon className="w-4 h-4 text-brand-400 mb-2" />
              <p className="text-sm font-medium mb-1">{label}</p>
              <p className="text-xs text-[var(--text-muted)]">{detail}</p>
            </div>
          ))}
        </div>

        <form
          onSubmit={onSubmit}
          className="rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6 sm:p-8 space-y-4"
        >
          <div>
            <label htmlFor="email" className="block text-xs text-[var(--text-muted)] mb-1.5">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2.5 text-sm outline-none focus:border-brand-500"
              placeholder="you@company.com"
            />
          </div>

          <div>
            <label htmlFor="company" className="block text-xs text-[var(--text-muted)] mb-1.5">
              Company / project
            </label>
            <input
              id="company"
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              className="w-full rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2.5 text-sm outline-none focus:border-brand-500"
              placeholder="Optional"
            />
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="oss" className="block text-xs text-[var(--text-muted)] mb-1.5">
                Using OSS today?
              </label>
              <select
                id="oss"
                value={usingOss}
                onChange={(e) => setUsingOss(e.target.value)}
                className="w-full rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2.5 text-sm outline-none focus:border-brand-500"
              >
                <option value="yes">Yes — already self-hosting</option>
                <option value="planning">Planning to try OSS</option>
                <option value="cloud-only">Cloud only for now</option>
              </select>
            </div>
            <div>
              <label htmlFor="pain" className="block text-xs text-[var(--text-muted)] mb-1.5">
                Main pain
              </label>
              <select
                id="pain"
                value={pain}
                onChange={(e) => setPain(e.target.value)}
                className="w-full rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2.5 text-sm outline-none focus:border-brand-500"
              >
                <option value="telephony">Telephony / numbers / ngrok</option>
                <option value="compliance">Compliance / data residency</option>
                <option value="sso">Team SSO / audit</option>
                <option value="ops">Keeping infra updated</option>
                <option value="other">Other</option>
              </select>
            </div>
          </div>

          <button type="submit" className="w-full btn-primary shimmer-sweep py-3 rounded-xl text-sm font-medium">
            Join the waitlist
          </button>

          {submitted && (
            <p className="text-xs text-brand-400 text-center">
              {WAITLIST_URL
                ? 'Opened the waitlist form in a new tab.'
                : 'Opened your email client with a pre-filled waitlist message.'}
            </p>
          )}

          <p className="text-[11px] text-[var(--text-muted)] text-center">
            Prefer self-host? Start with{' '}
            <Link href="/login" className="text-brand-400 hover:underline">
              Dev Login
            </Link>{' '}
            and Tier 0 playground. Details in{' '}
            <a
              href="https://github.com/Hadi11223344/vocode-core/blob/main/docs/VOIA_CLOUD.md"
              className="text-brand-400 hover:underline"
              target="_blank"
              rel="noreferrer"
            >
              docs/VOIA_CLOUD.md
            </a>
            .
          </p>
        </form>
      </div>
    </div>
  );
}
