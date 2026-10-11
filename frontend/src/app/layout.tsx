import type { Metadata, Viewport } from 'next';
import './globals.css';
import { AuthProvider } from '@/lib/auth-context';
import { ToastProvider } from '@/components/ui/toast';
import { ThemeProvider } from '@/components/ui/theme-provider';
import ErrorBoundary from '@/components/ui/error-boundary';
import { CursorFollower } from '@/components/ui/cursor-follower';

export const metadata: Metadata = {
  title: 'VOIA — Voice AI Agent Platform',
  description: 'Build, deploy, and manage AI voice agents',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 5,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const structuredData = {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'Organization',
        '@id': 'https://voia.ai/#organization',
        name: 'VOIA',
        url: 'https://voia.ai',
        logo: 'https://voia.ai/logo.svg',
        description: 'Voice AI Agent Platform - Build, deploy, and manage AI voice agents',
        sameAs: [
          'https://twitter.com/voiceaiagents',
          'https://linkedin.com/company/voiceaiagents',
        ],
        contactPoint: {
          '@type': 'ContactPoint',
          contactType: 'Customer Support',
          email: 'support@voia.ai',
        },
      },
      {
        '@type': 'WebSite',
        '@id': 'https://voia.ai/#website',
        url: 'https://voia.ai',
        name: 'VOIA',
        publisher: { '@id': 'https://voia.ai/#organization' },
      },
      {
        '@type': 'BreadcrumbList',
        '@id': 'https://voia.ai/#breadcrumb',
        itemListElement: [
          {
            '@type': 'ListItem',
            position: 1,
            name: 'Home',
            item: 'https://voia.ai',
          },
          {
            '@type': 'ListItem',
            position: 2,
            name: 'Features',
            item: 'https://voia.ai/#features',
          },
          {
            '@type': 'ListItem',
            position: 3,
            name: 'Integrations',
            item: 'https://voia.ai/#integrations',
          },
          {
            '@type': 'ListItem',
            position: 4,
            name: 'Pricing',
            item: 'https://voia.ai/#pricing',
          },
          {
            '@type': 'ListItem',
            position: 5,
            name: 'FAQ',
            item: 'https://voia.ai/#faq',
          },
        ],
      },
      {
        '@type': 'FAQPage',
        '@id': 'https://voia.ai/#faqpage',
        mainEntity: [
          {
            '@type': 'Question',
            name: 'What is VOIA?',
            acceptedAnswer: {
              '@type': 'Answer',
              text: 'VOIA is a voice AI agent platform that allows you to build, deploy, and manage production-ready AI voice agents with custom system prompts, multi-turn memory, and real-time function calling.',
            },
          },
          {
            '@type': 'Question',
            name: 'How much does VOIA cost?',
            acceptedAnswer: {
              '@type': 'Answer',
              text: 'VOIA uses transparent per-minute pricing starting at $0.07-0.15/min, with $10 free credits included. No platform fees.',
            },
          },
          {
            '@type': 'Question',
            name: 'Can I start for free?',
            acceptedAnswer: {
              '@type': 'Answer',
              text: 'Yes! You get $10 in free credits to start. No credit card required. You only pay for what you use.',
            },
          },
          {
            '@type': 'Question',
            name: 'What integrations does VOIA support?',
            acceptedAnswer: {
              '@type': 'Answer',
              text: 'VOIA has 30+ pre-built integrations including CRM (HubSpot), messaging (Slack), calendars, payments, and more. You can also build custom integrations with webhooks and our REST API.',
            },
          },
          {
            '@type': 'Question',
            name: 'Is VOIA HIPAA compliant?',
            acceptedAnswer: {
              '@type': 'Answer',
              text: 'Yes! VOIA is SOC 2 Type II certified, HIPAA compliant, and GDPR certified. Enterprise plans include dedicated infrastructure and 99.99% uptime SLA.',
            },
          },
        ],
      },
    ],
  };

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
        />
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('voia-theme');if(!t){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}document.documentElement.classList.add(t);}catch(e){document.documentElement.classList.add('dark');}})();`,
          }}
        />
      </head>
      <body className="antialiased">
        <ThemeProvider>
          <AuthProvider>
            <ToastProvider>
              <ErrorBoundary>
                <CursorFollower />
                {children}
              </ErrorBoundary>
            </ToastProvider>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
