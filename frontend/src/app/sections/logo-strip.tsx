'use client';

const LOGOS = [
  { name: 'Twilio', color: '#F22F46' },
  { name: 'OpenAI', color: '#10A37F' },
  { name: 'Deepgram', color: '#13EF93' },
  { name: 'ElevenLabs', color: '#818CF8' },
  { name: 'Vonage', color: '#E6E6E6' },
  { name: 'Anthropic', color: '#D97757' },
  { name: 'Google Cloud', color: '#4285F4' },
  { name: 'Groq', color: '#F55036' },
];

export default function LogoStrip() {
  const doubled = [...LOGOS, ...LOGOS];
  return (
    <section className="py-14">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <p className="text-center text-xs text-[var(--text-muted)] uppercase tracking-wider mb-8">
          Trusted by 850+ teams &middot; Powered by leading AI &amp; telephony providers
        </p>
        <div className="marquee-pause overflow-hidden relative">
          <div className="marquee-track gap-8 sm:gap-12 lg:gap-16">
            {doubled.map((logo, i) => (
              <span
                key={i}
                className="text-sm font-semibold whitespace-nowrap tracking-wide transition-all duration-300 hover:scale-110"
                style={{ color: 'var(--text-muted)' }}
                onMouseEnter={(e) => { e.currentTarget.style.color = logo.color; }}
                onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; }}
              >
                {logo.name}
              </span>
            ))}
          </div>
          <div className="absolute inset-y-0 left-0 w-20 bg-gradient-to-r from-[var(--bg-primary)] to-transparent pointer-events-none" />
          <div className="absolute inset-y-0 right-0 w-20 bg-gradient-to-l from-[var(--bg-primary)] to-transparent pointer-events-none" />
        </div>
      </div>
    </section>
  );
}
