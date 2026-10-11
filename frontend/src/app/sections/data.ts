import {
  Bot, Phone, GitBranch, BarChart3, Plug, Zap,
  Headphones, TrendingUp, Calendar, Building2, ShoppingCart, Stethoscope,
} from 'lucide-react';

export const FEATURES = [
  { icon: Bot, title: 'Intelligent AI Agents', description: 'Build agents with custom system prompts, multi-turn memory, personality tuning, and real-time function calling. Your agent sounds human, not robotic.', highlight: 'Custom prompts & tools' },
  { icon: Phone, title: 'Full Telephony Stack', description: 'Handle inbound calls, launch outbound campaigns, navigate IVR trees, detect answering machines, and transfer calls — all from one platform.', highlight: 'Inbound + Outbound' },
  { icon: GitBranch, title: 'Visual Workflow Builder', description: 'Drag-and-drop automation editor with conditional logic, delays, and 30+ integration actions. Trigger workflows from call events automatically.', highlight: 'No-code automation' },
  { icon: BarChart3, title: 'Deep Analytics', description: 'Track call volume, duration, cost-per-call, sentiment scores, and conversion rates. Export data and set up alerts for anomalies.', highlight: 'Real-time insights' },
  { icon: Plug, title: 'Limitless Integrations (MCP)', description: 'Connect to any external service dynamically using Model Context Protocol (MCP) servers or Custom Webhooks. The LLM discovers your tools automatically.', highlight: 'Your entire stack' },
  { icon: Zap, title: 'Sub-second Latency', description: 'Live call monitoring, WebSocket streaming, and in-call tool execution. Actions fire during the conversation, not after — book meetings while talking.', highlight: '< 800ms response' },
];

export const INTEGRATIONS = [
  { name: 'Twilio', color: '#F22F46', category: 'Telephony' },
  { name: 'Vonage', color: '#E6E6E6', category: 'Telephony' },
  { name: 'OpenAI', color: '#10A37F', category: 'AI / LLM' },
  { name: 'Google Gemini', color: '#4285F4', category: 'AI / LLM' },
  { name: 'Anthropic', color: '#D97757', category: 'AI / LLM' },
  { name: 'Groq', color: '#F55036', category: 'AI / LLM' },
  { name: 'Deepgram', color: '#13EF93', category: 'Speech' },
  { name: 'ElevenLabs', color: '#818CF8', category: 'Speech' },
  { name: 'Cartesia', color: '#FF7A59', category: 'Speech' },
  { name: 'Azure Speech', color: '#00A1E0', category: 'Speech' },
  { name: 'MCP Server', color: '#21A366', category: 'Extensibility' },
  { name: 'Custom Webhooks', color: '#6D00CC', category: 'Extensibility' },
];

export const SHOWCASES = [
  { title: 'Create AI agents in seconds', description: 'Design voice agents with natural personalities, knowledge bases, and live tool execution. Choose from 10+ voice providers and fine-tune every dial.', bullets: ['Custom system prompts & personality', 'Multi-provider voice selection (ElevenLabs, Deepgram, etc.)', 'Function calling — book meetings, send SMS during calls', 'Temperature, max tokens & response controls'], visual: 'agent' },
  { title: 'Automate with visual workflows', description: 'Build complex post-call and real-time automation flows with a drag-and-drop node editor. No code required.', bullets: ['Drag-and-drop node editor with ReactFlow', 'Conditional branching, delays & loops', 'Model Context Protocol (MCP) & Custom API Webhooks', 'Post-call triggers & real-time in-call execution'], visual: 'workflow' },
  { title: 'Monitor everything in real-time', description: 'Track active calls as they happen, review full transcripts and recordings, analyze cost and sentiment.', bullets: ['Live call dashboard with WebSocket updates', 'Full transcript, recording & summary access', 'Per-call cost tracking & budget alerts', 'Sentiment scoring & quality analysis'], visual: 'dashboard' },
];

export const USE_CASES = [
  { icon: Headphones, title: 'Customer Support', description: 'Automate L1 support calls, route complex issues to humans, and resolve queries 24/7 without hold times.', metric: '73% calls resolved' },
  { icon: TrendingUp, title: 'Sales & Lead Qualification', description: 'Qualify inbound leads, book demo meetings, and follow up on outbound campaigns automatically.', metric: '3.2x more meetings' },
  { icon: Calendar, title: 'Appointment Booking', description: 'Let AI handle scheduling, rescheduling, and reminders by connecting your scheduling system via MCP.', metric: '89% booking rate' },
  { icon: Building2, title: 'AI Receptionist', description: 'Answer every call, route to the right department, take messages, and handle after-hours inquiries.', metric: '0 missed calls' },
  { icon: ShoppingCart, title: 'Order Status & Returns', description: 'Give callers instant order updates, process returns, and manage refunds using dynamic Custom API lookups.', metric: '4.2min avg call' },
  { icon: Stethoscope, title: 'Healthcare Intake', description: 'Collect patient information, verify insurance, schedule appointments, and send reminders — HIPAA ready.', metric: '60% less no-shows' },
];

export const FAQS: { q: string; a: string }[] = [
  { q: 'How much does VOIA cost per minute?', a: 'VOIA uses transparent usage-based pricing. The total cost per minute is the sum of the voice engine ($0.05/min), your chosen LLM, and telephony. With GPT-4o and Twilio, a typical call costs around $0.11–0.15/min. No platform fees or hidden charges.' },
  { q: 'Is there a free tier?', a: 'Yes — every account starts with $10 in free credits (roughly 70–90 minutes of calling). No credit card required. Build and test your agents before spending a cent.' },
  { q: 'Can I bring my own LLM, voice, or telephony provider?', a: 'Absolutely. VOIA supports any OpenAI-compatible LLM (including self-hosted models), multiple TTS providers (ElevenLabs, Deepgram, PlayHT, etc.), and BYO Twilio/Vonage accounts so you keep your existing phone numbers.' },
  { q: 'How does concurrent call scaling work?', a: 'You get 5 concurrent calls included. Need more? Add capacity at $15/line/month, or contact us for unlimited concurrency on Enterprise. Scaling is instant — no downtime.' },
  { q: 'Is VOIA HIPAA compliant?', a: 'Yes. Our Enterprise plan includes BAA signing, encrypted data at rest and in transit, zero data retention options, and SOC 2 Type II compliance. We also support geo-based data residency.' },
  { q: 'What integrations are supported?', a: 'VOIA uses the Model Context Protocol (MCP) and Custom Webhooks to provide limitless integration potential. Instead of relying on hardcoded, outdated vendor plugins, you simply provide your MCP server URL or Webhook endpoint, and your voice agents will dynamically discover and use your specific tools during live calls.' },
  { q: 'Can the AI agent take actions during a live call?', a: 'Yes — this is a core VOIA capability. Agents can book meetings, send SMS, query your CRM, check order status, transfer calls, and trigger any workflow step while still on the call.' },
  { q: 'How fast is the response time?', a: 'VOIA achieves sub-800ms voice-to-voice latency on average. We use streaming STT, streaming LLM generation, and streaming TTS in parallel to minimize perceived delay.' },
];
