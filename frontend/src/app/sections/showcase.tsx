'use client';

import { Bot, GitBranch, BarChart3, Database, Mail, MessageSquare, Phone, ChevronRight, Check } from 'lucide-react';
import { useInView } from './hooks';
import { SHOWCASES } from './data';
import { cn } from '@/lib/utils';

interface ShowcaseProps {
  title: string;
  description: string;
  bullets: string[];
  visual: string;
  reversed: boolean;
}

function AgentMockup() {
  return (
    <div className="p-5 space-y-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2"><Bot className="w-4 h-4 text-brand-400 icon-rotate-hover" /><span className="text-sm font-medium">Agent Configuration</span></div>
        <span className="badge bg-emerald-500/15 text-emerald-400 text-[10px]">Active</span>
      </div>
      <div className="space-y-3">
        <div><label className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Name</label><div className="input-base !py-2 text-sm mt-1">Sales Assistant</div></div>
        <div><label className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">System Prompt</label><div className="input-base !py-2 text-sm mt-1 h-16 text-[var(--text-secondary)]">You are a friendly sales assistant for Acme Corp. Help callers with product questions, pricing, and scheduling demos...</div></div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Voice</label><div className="input-base !py-2 text-sm mt-1 flex items-center justify-between"><span>Aria (Natural)</span><ChevronRight className="w-3 h-3 text-[var(--text-muted)]" /></div></div>
          <div><label className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">LLM</label><div className="input-base !py-2 text-sm mt-1 flex items-center justify-between"><span>GPT-4o</span><ChevronRight className="w-3 h-3 text-[var(--text-muted)]" /></div></div>
        </div>
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-2 block">Tools</label>
          <div className="flex flex-wrap gap-2">
            {['Book Meeting', 'Send SMS', 'Search KB', 'Transfer Call'].map((t) => (<span key={t} className="badge bg-[var(--accent-muted)] text-brand-300 text-[10px]">{t}</span>))}
          </div>
        </div>
      </div>
    </div>
  );
}

function WorkflowMockup() {
  const nodes = [
    { icon: Phone, color: 'emerald', label: 'Call Completed', sub: 'Trigger: transcript_complete' },
    { icon: Database, color: 'brand', label: 'Save to HubSpot', sub: 'Action: create_contact' },
    { icon: Mail, color: 'purple', label: 'Send Follow-up Email', sub: 'Action: send_email via SMTP' },
    { icon: MessageSquare, color: 'pink', label: 'Notify Slack Channel', sub: 'Action: send_message to #sales' },
  ];
  return (
    <div className="p-5">
      <div className="flex items-center gap-2 mb-4"><GitBranch className="w-4 h-4 text-brand-400 icon-rotate-hover" /><span className="text-sm font-medium">Post-Call Workflow</span></div>
      <div className="space-y-3">
        {nodes.map((n, i) => (
          <div key={n.label}>
            <div className="flex items-center gap-3">
              <div className={`w-8 h-8 rounded-lg bg-${n.color}-500/15 flex items-center justify-center flex-shrink-0`}><n.icon className={`w-3.5 h-3.5 text-${n.color}-400`} /></div>
              <div className="flex-1 card-base p-3"><p className="text-xs font-medium">{n.label}</p><p className="text-[10px] text-[var(--text-muted)]">{n.sub}</p></div>
            </div>
            {i < nodes.length - 1 && <div className="flex items-center gap-3 py-1"><div className="w-8 flex justify-center"><div className="w-px h-5 bg-[var(--border-color)]" /></div></div>}
          </div>
        ))}
      </div>
    </div>
  );
}

function DashboardMockup() {
  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2"><BarChart3 className="w-4 h-4 text-brand-400 icon-pulse-hover" /><span className="text-sm font-medium">Analytics</span></div>
        <span className="text-[10px] text-[var(--text-muted)]">Mar 2026</span>
      </div>
      <div className="grid grid-cols-3 gap-3 mb-4">
        {[
          { label: 'Calls Today', value: '284', color: 'text-brand-400' },
          { label: 'Avg. Sentiment', value: '8.4/10', color: 'text-emerald-400' },
          { label: 'Cost', value: '$42.60', color: 'text-amber-400' },
        ].map((m) => (
          <div key={m.label} className="bg-[var(--bg-secondary)] rounded-lg p-3">
            <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">{m.label}</p>
            <p className={cn('text-lg font-bold mt-0.5', m.color)}>{m.value}</p>
          </div>
        ))}
      </div>
      <div className="bg-[var(--bg-secondary)] rounded-lg overflow-hidden">
        <div className="grid grid-cols-4 gap-2 px-3 py-2 border-b border-[var(--border-color)]">
          {['Caller', 'Agent', 'Duration', 'Status'].map((h) => (<span key={h} className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">{h}</span>))}
        </div>
        {[
          { caller: '+1 (555) 0134', agent: 'Sales Bot', dur: '4m 12s', status: 'completed' },
          { caller: '+1 (555) 0891', agent: 'Support AI', dur: '2m 08s', status: 'completed' },
          { caller: '+1 (555) 0467', agent: 'Booking', dur: '1m 55s', status: 'transferred' },
        ].map((r) => (
          <div key={r.caller} className="grid grid-cols-4 gap-2 px-3 py-2 border-b border-[var(--border-color)] last:border-0">
            <span className="text-[11px] font-mono text-[var(--text-secondary)]">{r.caller}</span>
            <span className="text-[11px]">{r.agent}</span>
            <span className="text-[11px] text-[var(--text-muted)]">{r.dur}</span>
            <span className={cn('text-[10px] font-medium', r.status === 'completed' ? 'text-emerald-400' : 'text-amber-400')}>{r.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ShowcaseSection({ title, description, bullets, visual, reversed }: ShowcaseProps) {
  const { ref, inView } = useInView();
  return (
    <section className="py-20 sm:py-28">
      <div ref={ref} className={cn('max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-20 items-center', inView ? 'animate-fade-in' : 'opacity-0')}>
        <div className={cn(reversed && 'lg:order-2')}>
          <h3 className="text-2xl sm:text-3xl font-bold tracking-tight mb-4">{title}</h3>
          <p className="text-[var(--text-secondary)] leading-relaxed mb-6">{description}</p>
          <ul className="space-y-3">
            {bullets.map((b) => (
              <li key={b} className="flex items-start gap-3">
                <div className="mt-0.5 w-5 h-5 rounded-full bg-brand-500/15 flex items-center justify-center flex-shrink-0"><Check className="w-3 h-3 text-brand-400" /></div>
                <span className="text-sm text-[var(--text-secondary)]">{b}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className={cn(reversed && 'lg:order-1')}>
          <div className="relative">
            <div className="absolute -inset-3 bg-gradient-to-br from-brand-600/[0.08] to-purple-600/[0.04] rounded-2xl blur-xl" />
            <div data-tilt-card className="relative glass-card rounded-2xl overflow-hidden tilt-card">
              <div className="glass-card-border" />
              {visual === 'agent' && <AgentMockup />}
              {visual === 'workflow' && <WorkflowMockup />}
              {visual === 'dashboard' && <DashboardMockup />}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
