'use client';

import { Bot, Check } from 'lucide-react';
import { useInView } from './hooks';
import { cn } from '@/lib/utils';
import dynamic from 'next/dynamic';

const VoiceWaveform = dynamic(() => import('@/components/landing/VoiceWaveform'), { ssr: false });

export default function ConversationDemo() {
  const { ref, inView } = useInView();
  const messages = [
    { role: 'agent' as const, text: "Hello! Thanks for calling Acme Corp. I'm Sarah, your AI assistant. How can I help you today?", delay: 0 },
    { role: 'caller' as const, text: "Hi Sarah, I'd like to schedule a demo of your enterprise plan.", delay: 0.8 },
    { role: 'agent' as const, text: "I'd be happy to help! Let me check available slots. I see openings this Thursday at 2 PM or Friday at 10 AM. Which works better?", delay: 1.6 },
    { role: 'caller' as const, text: "Thursday at 2 PM works perfectly.", delay: 2.4 },
    { role: 'action' as const, text: '\u{1F4C5} Meeting booked: Thursday 2:00 PM \u2014 Synced to Google Calendar', delay: 3.2 },
    { role: 'action' as const, text: '\u{1F4E7} Confirmation email sent via SMTP', delay: 3.35 },
    { role: 'action' as const, text: '\u{1F4BC} Contact created in HubSpot CRM', delay: 3.5 },
    { role: 'agent' as const, text: "Done! I've booked Thursday at 2 PM and sent you a confirmation email. Our sales team will be ready for you. Anything else?", delay: 4.2 },
  ];

  return (
    <section className="py-24 sm:py-32 bg-[var(--bg-secondary)]/50">
      <div ref={ref} className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
          <div>
            <p className="text-sm font-medium text-brand-400 mb-3">See It In Action</p>
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight mb-4">Watch your AI agent <span className="text-gradient-animated">handle a real call</span></h2>
            <p className="text-[var(--text-secondary)] leading-relaxed mb-6">This is what a typical inbound call looks like with VOIA. The agent understands intent, takes actions in real-time, and updates your systems &mdash; all while keeping the conversation natural.</p>
            <ul className="space-y-3">
              {['Natural multi-turn conversation', 'Books meetings during the call', 'Syncs data to CRM automatically', 'Sends confirmation emails in real-time'].map((item) => (
                <li key={item} className="flex items-center gap-3">
                  <div className="w-5 h-5 rounded-full bg-brand-500/15 flex items-center justify-center flex-shrink-0"><Check className="w-3 h-3 text-brand-400" /></div>
                  <span className="text-sm text-[var(--text-secondary)]">{item}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className={cn('transition-all duration-700', inView ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8')}>
            <div className="relative">
              <div className="absolute -inset-3 bg-gradient-to-br from-brand-600/[0.08] to-purple-600/[0.04] rounded-2xl blur-xl" />
              <div data-tilt-card className="relative glass-card rounded-2xl overflow-hidden tilt-card">
                <div className="glass-card-border" />
                <div className="flex items-center gap-3 px-5 py-3 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]/50">
                  <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="text-xs font-medium">Live Call &mdash; Sales Agent</span>
                  <div className="ml-auto flex items-center gap-3">
                    <VoiceWaveform bars={20} className="h-5 w-16" color="#22c55e" />
                    <span className="text-[10px] text-[var(--text-muted)] font-mono">00:47</span>
                  </div>
                </div>
                <div className="p-4 space-y-3 max-h-[420px] overflow-y-auto">
                  {messages.map((msg, i) => (
                    <div key={i} className={cn('transition-all duration-500', inView ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4', msg.role === 'caller' && 'flex justify-end', msg.role === 'action' && 'flex justify-center')} style={{ transitionDelay: inView ? `${msg.delay * 600}ms` : '0ms' }}>
                      {msg.role === 'agent' && (
                        <div className="flex gap-2.5 max-w-[85%]">
                          <div className="w-7 h-7 rounded-lg gradient-brand flex items-center justify-center flex-shrink-0 mt-0.5"><Bot className="w-3.5 h-3.5 text-white" /></div>
                          <div className="glass-card rounded-xl rounded-tl-sm px-3.5 py-2.5"><p className="text-[13px] text-[var(--text-secondary)] leading-relaxed">{msg.text}</p></div>
                        </div>
                      )}
                      {msg.role === 'caller' && (
                        <div className="bg-brand-600/20 rounded-xl rounded-tr-sm px-3.5 py-2.5 max-w-[85%]"><p className="text-[13px] text-brand-200 leading-relaxed">{msg.text}</p></div>
                      )}
                      {msg.role === 'action' && (
                        <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-1.5 max-w-[90%]"><p className="text-[11px] text-emerald-400 font-medium">{msg.text}</p></div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
