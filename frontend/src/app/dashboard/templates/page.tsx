'use client';

import { useEffect, useState, useMemo, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { agents as agentsApi, integrations as integrationsApi, knowledgeBases as knowledgeBasesApi } from '@/lib/api';
import { Integration } from '@/lib/types';
import { useToast } from '@/components/ui/toast';
import {
  Search,
  Sparkles,
  ArrowRight,
  Clock,
  Phone,
  PhoneOutgoing,
  MessageSquare,
  X,
  Check,
  Copy,
  Play,
  Filter,
  Wand2,
  Bot,
  Loader2,
  ChevronRight,
  Info,
  BookOpen,
  Zap,
  GraduationCap,
  Megaphone,
  HeartPulse,
  ShoppingCart,
  Headset,
  TrendingUp,
  CalendarCheck,
  UtensilsCrossed,
  Stethoscope,
  Package,
  Home,
  Languages,
  Users,
  FlaskConical,
  ChevronDown,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import Link from 'next/link';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';

/* ─── Types ─────────────────────────────────────────────── */
interface AgentTemplate {
  id: string;
  slug: string;
  name: string;
  tagline: string;
  description: string;
  category: string;
  mode: string;
  icon: string;
  color: string;
  demo_script: string;
  adversarial_test_cases?: string[];
  recommended_tools: string[];
  outbound_ready: boolean;
  inbound_ready: boolean;
  estimated_setup_time: string;
  features: string[];
  setup_notes?: string;
}

/* ─── Icon mapping ────────────────────────────────────── */
const ICON_MAP: Record<string, LucideIcon> = {
  Headset,
  TrendingUp,
  CalendarCheck,
  Phone,
  UtensilsCrossed,
  Stethoscope,
  Package,
  MessageCircleHeart: HeartPulse,
  Home,
  Languages,
  BookOpen,
  Users,
  ShoppingCart,
  GraduationCap,
  Megaphone,
  HeartPulse,
};

function getIcon(name: string): LucideIcon {
  return ICON_MAP[name] || Bot;
}

/* ─── Color mapping ───────────────────────────────────── */
const COLOR_STYLES: Record<string, { bg: string; border: string; text: string; badge: string; ring: string; glow: string }> = {
  cyan:    { bg: 'bg-cyan-500/10',  border: 'border-cyan-500/20',  text: 'text-cyan-400',  badge: 'bg-cyan-500/15 text-cyan-300',  ring: 'ring-cyan-500/30',  glow: 'shadow-cyan-500/10' },
  amber:   { bg: 'bg-amber-500/10', border: 'border-amber-500/20', text: 'text-amber-400', badge: 'bg-amber-500/15 text-amber-300', ring: 'ring-amber-500/30', glow: 'shadow-amber-500/10' },
  emerald: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', text: 'text-emerald-400', badge: 'bg-emerald-500/15 text-emerald-300', ring: 'ring-emerald-500/30', glow: 'shadow-emerald-500/10' },
  violet:  { bg: 'bg-violet-500/10', border: 'border-violet-500/20', text: 'text-violet-400', badge: 'bg-violet-500/15 text-violet-300', ring: 'ring-violet-500/30', glow: 'shadow-violet-500/10' },
  rose:    { bg: 'bg-rose-500/10',  border: 'border-rose-500/20',  text: 'text-rose-400',  badge: 'bg-rose-500/15 text-rose-300',  ring: 'ring-rose-500/30',  glow: 'shadow-rose-500/10' },
  teal:    { bg: 'bg-teal-500/10',  border: 'border-teal-500/20',  text: 'text-teal-400',  badge: 'bg-teal-500/15 text-teal-300',  ring: 'ring-teal-500/30',  glow: 'shadow-teal-500/10' },
  orange:  { bg: 'bg-orange-500/10', border: 'border-orange-500/20', text: 'text-orange-400', badge: 'bg-orange-500/15 text-orange-300', ring: 'ring-orange-500/30', glow: 'shadow-orange-500/10' },
  pink:    { bg: 'bg-pink-500/10',  border: 'border-pink-500/20',  text: 'text-pink-400',  badge: 'bg-pink-500/15 text-pink-300',  ring: 'ring-pink-500/30',  glow: 'shadow-pink-500/10' },
  sky:     { bg: 'bg-sky-500/10',   border: 'border-sky-500/20',   text: 'text-sky-400',   badge: 'bg-sky-500/15 text-sky-300',   ring: 'ring-sky-500/30',   glow: 'shadow-sky-500/10' },
  indigo:  { bg: 'bg-indigo-500/10', border: 'border-indigo-500/20', text: 'text-indigo-400', badge: 'bg-indigo-500/15 text-indigo-300', ring: 'ring-indigo-500/30', glow: 'shadow-indigo-500/10' },
  blue:    { bg: 'bg-blue-500/10',   border: 'border-blue-500/20',   text: 'text-blue-400',   badge: 'bg-blue-500/15 text-blue-300',   ring: 'ring-blue-500/30',   glow: 'shadow-blue-500/10' },
};

function getColorStyles(color: string) {
  return COLOR_STYLES[color] || COLOR_STYLES.cyan;
}

/* ─── Categories ──────────────────────────────────────── */
const CATEGORIES = [
  { id: 'all', label: 'All Templates', count: null as number | null },
  { id: 'support', label: 'Support', count: null },
  { id: 'sales', label: 'Sales', count: null },
  { id: 'healthcare', label: 'Healthcare', count: null },
  { id: 'hospitality', label: 'Hospitality', count: null },
  { id: 'ecommerce', label: 'E-Commerce', count: null },
  { id: 'realestate', label: 'Real Estate', count: null },
  { id: 'education', label: 'Education', count: null },
  { id: 'general', label: 'General', count: null },
];

/* ─── Static fallback templates (shown while loading or on error) ─ */
const FALLBACK_TEMPLATES: AgentTemplate[] = [
  {
    id: 'support', slug: 'customer-support', name: 'Customer Support Agent',
    tagline: 'Resolve issues 24/7 with empathy and speed',
    description: 'Handles inbound support calls: answers FAQs, troubleshoots, checks orders, and escalates.',
    category: 'support', mode: 'single_prompt', icon: 'Headset', color: 'cyan',
    demo_script: 'Caller: "Hi, my order hasn\'t arrived yet."\nExpected: Agent asks for order number, empathizes, offers solution.',
    adversarial_test_cases: [],
    recommended_tools: ['read_sheet', 'append_sheet', 'webhook'],
    outbound_ready: false, inbound_ready: true, estimated_setup_time: '2 min',
    features: ['FAQ auto-answers', 'Order lookup ready', 'Human escalation trigger', 'Empathy-first tone'],
  },
  {
    id: 'sales', slug: 'sales-qualifier', name: 'Sales Lead Qualifier',
    tagline: 'Qualify leads and book demos while you sleep',
    description: 'Outbound sales agent that calls leads, qualifies them with BANT, and books demos.',
    category: 'sales', mode: 'single_prompt', icon: 'TrendingUp', color: 'amber',
    demo_script: 'Lead: "What do you guys actually do?"\nExpected: 20-second pitch, qualifying questions, demo offer.',
    adversarial_test_cases: [],
    recommended_tools: ['check_calendar', 'book_appointment', 'send_email'],
    outbound_ready: true, inbound_ready: false, estimated_setup_time: '3 min',
    features: ['BANT qualification', 'Demo booking ready', 'Objection handling', 'DNC/compliance aware'],
  },
  {
    id: 'scheduler', slug: 'appointment-scheduler', name: 'Appointment Scheduler',
    tagline: 'Book, reschedule, and cancel appointments — no human needed',
    description: 'Multi-step conversational agent for clinics and service businesses.',
    category: 'healthcare', mode: 'conversational_flow', icon: 'CalendarCheck', color: 'emerald',
    demo_script: 'Caller: "I need a dental cleaning next week."\nExpected: Collect info, offer slots, confirm.',
    adversarial_test_cases: [],
    recommended_tools: ['check_calendar', 'book_appointment', 'send_sms', 'send_email'],
    outbound_ready: true, inbound_ready: true, estimated_setup_time: '3 min',
    features: ['Multi-step booking flow', 'Reschedule & cancel', 'SMS reminder ready', 'Emergency triage routing'],
  },
  {
    id: 'receptionist', slug: 'virtual-receptionist', name: 'Virtual Receptionist',
    tagline: 'Answer every call. Route perfectly. Never miss a lead.',
    description: 'Professional front-desk agent that greets, routes, and takes messages 24/7.',
    category: 'general', mode: 'single_prompt', icon: 'Phone', color: 'violet',
    demo_script: 'Caller: "I\'d like to speak to someone about pricing."\nExpected: Routes to sales or takes message.',
    adversarial_test_cases: [],
    recommended_tools: ['webhook'],
    outbound_ready: false, inbound_ready: true, estimated_setup_time: '2 min',
    features: ['Smart call routing', 'Message taking', 'After-hours handling', 'Department directory'],
  },
  {
    id: 'drive_kb', slug: 'drive-knowledge-employee', name: 'Google Drive Knowledge Agent',
    tagline: 'Answer any question by reading your company documents live',
    description: 'Inbound agent that reads bound Google Drive documents in real time to answer FAQs.',
    category: 'support', mode: 'single_prompt', icon: 'BookOpen', color: 'blue',
    demo_script: 'Caller: "What are your delivery charges?"\nExpected: Agent reads Drive doc, answers naturally.',
    adversarial_test_cases: [],
    recommended_tools: ['read_drive_file', 'recall_document'],
    outbound_ready: false, inbound_ready: true, estimated_setup_time: '2 min',
    features: ['Real-time Drive reading', 'Cross-call document memory', 'Honest escalation', 'Natural summarization'],
  },
  {
    id: 'crm', slug: 'voice-crm-lead-capture', name: 'Voice CRM Lead Capture',
    tagline: 'Capture leads by voice and log them straight to your spreadsheet',
    description: 'Qualifies callers, captures details, and appends them to a Google Sheet CRM.',
    category: 'sales', mode: 'single_prompt', icon: 'Users', color: 'indigo',
    demo_script: 'Caller: "I want a quotation for a website."\nExpected: Collects details, logs to Sheet, sends confirmation.',
    adversarial_test_cases: [],
    recommended_tools: ['append_sheet', 'read_sheet', 'send_email', 'send_sms'],
    outbound_ready: false, inbound_ready: true, estimated_setup_time: '3 min',
    features: ['Lead qualification', 'Auto-log to Sheets', 'Multi-channel confirmation', 'Budget capture'],
  },
  {
    id: 'sales_catalog', slug: 'ecommerce-sales-agent', name: 'E-commerce Sales Agent',
    tagline: 'Browse products, check stock, and capture orders by voice',
    description: 'Reads product catalogs from Drive and inventory from Sheets to help customers buy.',
    category: 'ecommerce', mode: 'single_prompt', icon: 'ShoppingCart', color: 'orange',
    demo_script: 'Caller: "Which laptop is best for video editing under $1000?"\nExpected: Reads catalog, checks stock, recommends, captures lead.',
    adversarial_test_cases: [],
    recommended_tools: ['read_drive_file', 'read_sheet', 'append_sheet', 'send_email', 'send_sms', 'recall_document'],
    outbound_ready: false, inbound_ready: true, estimated_setup_time: '3 min',
    features: ['Live product catalog', 'Real-time inventory', 'Product comparison', 'Lead capture', 'Multi-channel sharing'],
  },
  {
    id: 'university', slug: 'university-admission-agent', name: 'University Admission Agent',
    tagline: 'Answer admission queries 24/7 from your official documents',
    description: 'Reads admission docs from Drive and captures student inquiries to Sheets.',
    category: 'education', mode: 'single_prompt', icon: 'GraduationCap', color: 'teal',
    demo_script: 'Caller: "What is the fee for BSCS and are scholarships available?"\nExpected: Reads docs, answers clearly, captures lead.',
    adversarial_test_cases: [],
    recommended_tools: ['read_drive_file', 'recall_document', 'append_sheet', 'send_email', 'send_sms'],
    setup_notes: '1. Connect Google Drive for admission documents. 2. Connect Google Sheets to log inquiries. 3. Connect Email (SMTP) to send confirmations.',
    outbound_ready: false, inbound_ready: true, estimated_setup_time: '2 min',
    features: ['Document-based answers', 'Program & fee lookup', 'Scholarship guidance', 'Student inquiry capture', 'Multi-channel sharing'],
  },
  {
    id: 'umt_outreach', slug: 'umt-outreach-sales', name: 'UMT Outreach & Sales',
    tagline: 'Proactive counselor that qualifies leads and drives admissions',
    description: 'Calls prospective students, highlights UMT value, calculates scholarships, and encourages applications. Ethical persuasion with no pressure.',
    category: 'sales', mode: 'single_prompt', icon: 'Megaphone', color: 'indigo',
    demo_script: 'Lead: "I am also considering FAST and LUMS."\nExpected: Acknowledges competitors, highlights UMT value (lower fees, scholarships, placement), offers campus visit.',
    adversarial_test_cases: [],
    recommended_tools: ['append_sheet', 'check_calendar', 'book_appointment', 'send_sms', 'send_email'],
    setup_notes: '1. Connect Google Calendar for appointment booking. 2. Connect Google Sheets to log lead details. 3. Connect Email (SMTP) for follow-ups. 4. (Optional) Connect SMS for appointment reminders.',
    outbound_ready: true, inbound_ready: false, estimated_setup_time: '3 min',
    features: ['Lead qualification', 'Scholarship assessment', 'Competitor comparison', 'Campus visit booking', 'Follow-up scheduling'],
  },
  {
    id: 'smilecare', slug: 'smilecare-dental', name: 'SmileCare Dental Receptionist',
    tagline: 'Book appointments, triage emergencies, answer patient questions — 24/7',
    description: 'Full-stack dental receptionist for SmileCare Dental Clinic, Lahore. Handles inbound calls (booking, emergency triage, FAQs) and outbound calls (reminders, follow-ups). KB-powered with Urdu-English bilingual support.',
    category: 'healthcare', mode: 'single_prompt', icon: 'HeartPulse', color: 'teal',
    demo_script: 'Caller: "Mujhe dant mein dard hai, appointment chahiye."\nExpected: Agent greets in Urdu/English, asks about pain severity, checks emergency red flags, schedules with appropriate dentist, logs to Sheets, sends SMS.',
    adversarial_test_cases: [],
    recommended_tools: ['read_sheet', 'append_sheet', 'check_calendar', 'book_appointment', 'send_sms', 'send_email', 'recall_document'],
    setup_notes: '1. Upload knowledge_base/dental_clinic.txt to Knowledge Bases and link it. 2. Connect Google Calendar for appointment booking. 3. Connect Google Sheets for patient records. 4. Connect Email (SMTP) for booking confirmations. 5. (Optional) Connect SMS for appointment reminders.',
    outbound_ready: true, inbound_ready: true, estimated_setup_time: '2 min',
    features: ['KB-powered answers (dentists, services, fees)', 'Emergency dental triage with red-flag detection', 'Appointment booking & rescheduling', 'Patient logging to Google Sheets', 'Insurance verification (EFU, Adamjee, Jubilee, TPL)', 'Discount awareness (family, student, senior, referral)', 'Outbound reminders & follow-ups', 'Urdu-English bilingual'],
  },
  {
    id: 'stylehub_sales', slug: 'stylehub-sales-agent', name: 'StyleHub.pk Sales Agent',
    tagline: 'Voice shopping assistant for fashion orders across Pakistan',
    description: 'Helps customers browse products, check inventory, place orders, and track deliveries. Logs orders to Sheets and sends confirmations via email.',
    category: 'ecommerce', mode: 'single_prompt', icon: 'ShoppingCart', color: 'pink',
    demo_script: 'Caller: "I need a lawn suit for Eid under PKR 4,000."\nExpected: Checks inventory, recommends WU-003 or WU-001, captures order details.',
    adversarial_test_cases: [],
    recommended_tools: ['read_sheet', 'append_sheet', 'send_sms', 'send_email'],
    setup_notes: '1. Connect Google Sheets for product catalog and order logging. 2. Connect Email (SMTP) for order confirmations. 3. (Optional) Connect SMS for delivery notifications.',
    outbound_ready: false, inbound_ready: true, estimated_setup_time: '3 min',
    features: ['Product catalog lookup', 'Order booking', 'Delivery calculation', 'COD support', 'Urdu-English bilingual'],
  },
];

/* ─── Main Page ───────────────────────────────────────── */
export default function TemplatesPage() {
  const router = useRouter();
  const toast = useToast();
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [activeCategory, setActiveCategory] = useState('all');
  const [selectedTemplate, setSelectedTemplate] = useState<AgentTemplate | null>(null);
  const [creating, setCreating] = useState(false);
  const [copiedDemo, setCopiedDemo] = useState(false);
  const [knowledgeBaseOptions, setKnowledgeBaseOptions] = useState<Array<{ id: number; name: string }>>([]);
  const [knowledgeBaseId, setKnowledgeBaseId] = useState<number | null>(null);
  const [driveOptions, setDriveOptions] = useState<Array<{ id: number; name: string }>>([]);
  const [driveIntegrationId, setDriveIntegrationId] = useState<number | null>(null);

  // Fetch templates
  useEffect(() => {
    let cancelled = false;
    agentsApi.templates()
      .then((res) => {
        if (!cancelled) {
          setTemplates(res.templates);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setTemplates(FALLBACK_TEMPLATES);
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, []);

    useEffect(() => {
      knowledgeBasesApi.list()
        .then((res) => {
          setKnowledgeBaseOptions(
            res.knowledge_bases.map((kb) => ({ id: kb.id, name: kb.name }))
          );
        })
        .catch(() => setKnowledgeBaseOptions([]));
    }, []);

    useEffect(() => {
      integrationsApi.list()
        .then((res) => {
          const driveIntegrations = res.integrations.filter(
            (i: Integration) => i.service_type === 'google_drive_mcp' && i.is_active
          );
          setDriveOptions(
            driveIntegrations.map((i: Integration) => ({ id: i.id, name: i.name }))
          );
        })
        .catch(() => setDriveOptions([]));
    }, []);

  // Filter templates
  const filtered = useMemo(() => {
    let result = templates;
    if (activeCategory !== 'all') {
      result = result.filter((t) => t.category === activeCategory);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (t) =>
          t.name.toLowerCase().includes(q) ||
          t.tagline.toLowerCase().includes(q) ||
          t.description.toLowerCase().includes(q) ||
          t.category.toLowerCase().includes(q)
      );
    }
    return result;
  }, [templates, activeCategory, search]);

  // Create agent from template
  const handleUseTemplate = useCallback(async (template: AgentTemplate) => {
    setCreating(true);
    try {
      const res = await agentsApi.fromTemplate({
        template_id: template.id,
        name: template.name,
        knowledge_base_id: knowledgeBaseId,
        google_drive_integration_id: driveIntegrationId,
      });
      if (template.mode === 'conversational_flow') {
        toast.success(`Agent "${res.agent.name}" created!`, 'Opening the workflow editor — design your flow and save to activate conversational flow mode.');
        router.push(`/dashboard/workflows/new?agentId=${res.agent.id}`);
      } else {
        toast.success(`Agent "${res.agent.name}" created!`);
        router.push(`/dashboard/playground?agent=${res.agent.id}`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to create agent';
      toast.error('Failed to create agent', msg);
      setCreating(false);
    }
  }, [knowledgeBaseId, driveIntegrationId, router, toast]);

  const copyDemoScript = useCallback((script: string) => {
    navigator.clipboard.writeText(script).then(() => {
      setCopiedDemo(true);
      setTimeout(() => setCopiedDemo(false), 2000);
    });
  }, []);

  return (
    <GsapPageWrapper>
    <div className="max-w-7xl mx-auto pb-12">
      {/* ── Header ── */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl bg-violet-500/15 flex items-center justify-center">
            <Sparkles size={20} className="text-violet-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">Agent Templates</h1>
            <p className="text-sm text-[var(--text-muted)]">
              Production-ready agents for every use case. Pick one, customize, and go live in minutes.
            </p>
          </div>
        </div>

        {/* ── Search & Filter Bar ── */}
        <div className="flex flex-col sm:flex-row gap-3 mt-6">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input
              type="text"
              placeholder="Search templates..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-9 pr-4 py-2.5 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-xl text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-violet-500/30"
            />
          </div>
          <div className="flex items-center gap-2 overflow-x-auto pb-1 sm:pb-0 scrollbar-hide">
            {CATEGORIES.map((cat) => (
              <button
                key={cat.id}
                onClick={() => setActiveCategory(cat.id)}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all',
                  activeCategory === cat.id
                    ? 'bg-violet-500/20 text-violet-300 border border-violet-500/30'
                    : 'bg-[var(--bg-secondary)] text-[var(--text-muted)] border border-[var(--border-color)] hover:text-[var(--text-primary)] hover:border-[var(--border-hover)]'
                )}
              >
                {cat.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Results count ── */}
      {!loading && (
        <p className="text-xs text-[var(--text-muted)] mb-4">
          {filtered.length} template{filtered.length !== 1 ? 's' : ''} found
          {activeCategory !== 'all' ? ` in "${CATEGORIES.find((c) => c.id === activeCategory)?.label}"` : ''}
        </p>
      )}

      {/* ── Template Grid ── */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="dash-skeleton rounded-2xl p-5">
              <div className="w-12 h-12 rounded-xl bg-[var(--bg-tertiary)] mb-4" />
              <div className="h-5 bg-[var(--bg-tertiary)] rounded w-3/4 mb-2" />
              <div className="h-4 bg-[var(--bg-tertiary)] rounded w-full mb-3" />
              <div className="h-3 bg-[var(--bg-tertiary)] rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="dash-card rounded-2xl p-12 text-center">
          <Search size={32} className="text-[var(--text-muted)] mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-1">No templates found</h3>
          <p className="text-sm text-[var(--text-muted)]">Try a different search or category.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {filtered.map((template) => {
            const Icon = getIcon(template.icon);
            const cs = getColorStyles(template.color);
            return (
              <div
                key={template.id}
                className={cn(
                  'group dash-card rounded-2xl p-5 border transition-all duration-200 cursor-pointer',
                  'hover:shadow-lg hover:-translate-y-0.5',
                  cs.border,
                  cs.glow
                )}
                onClick={() => {
                  setSelectedTemplate(template);
                  setKnowledgeBaseId(null);
                  setDriveIntegrationId(null);
                }}
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div className={cn('w-12 h-12 rounded-xl flex items-center justify-center', cs.bg)}>
                    <Icon size={22} className={cs.text} />
                  </div>
                  <div className="flex gap-1.5">
                    {template.inbound_ready && (
                      <span title="Receives calls" className="px-2 py-0.5 rounded-md text-[10px] font-medium bg-emerald-500/15 text-emerald-300 border border-emerald-500/20 flex items-center gap-1">
                        <Phone size={10} /> Inbound
                      </span>
                    )}
                    {template.outbound_ready && (
                      <span title="Makes calls" className="px-2 py-0.5 rounded-md text-[10px] font-medium bg-amber-500/15 text-amber-300 border border-amber-500/20 flex items-center gap-1">
                        <PhoneOutgoing size={10} /> Outbound
                      </span>
                    )}
                  </div>
                </div>

                {/* Title */}
                <h3 className="text-base font-semibold text-[var(--text-primary)] mb-1">{template.name}</h3>
                <p className={cn('text-xs font-medium mb-2', cs.text)}>{template.tagline}</p>
                <p className="text-sm text-[var(--text-muted)] leading-relaxed mb-4 line-clamp-2">
                  {template.description}
                </p>

                {/* Features */}
                <div className="flex flex-wrap gap-1.5 mb-4">
                  {template.features.slice(0, 3).map((f) => (
                    <span key={f} className="px-2 py-0.5 rounded-md text-[10px] font-medium bg-[var(--bg-tertiary)] text-[var(--text-muted)] border border-[var(--border-color)]">
                      {f}
                    </span>
                  ))}
                  {template.features.length > 3 && (
                    <span className="px-2 py-0.5 rounded-md text-[10px] font-medium bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
                      +{template.features.length - 3}
                    </span>
                  )}
                </div>

                {/* Footer */}
                <div className="flex items-center justify-between pt-3 border-t border-[var(--border-color)]">
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
                      <Clock size={12} />
                      <span>{template.estimated_setup_time} setup</span>
                    </div>
                    {template.recommended_tools.length > 0 && (
                      <div className="flex items-center gap-1 text-xs text-[var(--text-muted)]">
                        <Wand2 size={12} />
                        <span>{template.recommended_tools.length} integration{template.recommended_tools.length > 1 ? 's' : ''}</span>
                      </div>
                    )}
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleUseTemplate(template);
                    }}
                    disabled={creating}
                    className={cn(
                      'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
                      'bg-[var(--surface-hover)] text-[var(--text-primary)] hover:bg-[var(--bg-hover)] border border-[var(--glass-border)]',
                      creating && 'opacity-50 cursor-not-allowed'
                    )}
                  >
                    {creating ? (
                      <>
                        <Loader2 size={12} className="animate-spin" />
                        Creating...
                      </>
                    ) : (
                      <>
                        <Wand2 size={12} />
                        Use Template
                      </>
                    )}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Detail Modal ── */}
      {selectedTemplate && (
        <TemplateDetailModal
          template={selectedTemplate}
          onClose={() => {
            setSelectedTemplate(null);
            setKnowledgeBaseId(null);
          }}
          onUse={() => handleUseTemplate(selectedTemplate)}
          creating={creating}
          copiedDemo={copiedDemo}
          onCopyDemo={copyDemoScript}
          knowledgeBaseId={knowledgeBaseId}
          knowledgeBaseOptions={knowledgeBaseOptions}
          onChangeKnowledgeBaseId={setKnowledgeBaseId}
          driveIntegrationId={driveIntegrationId}
          driveOptions={driveOptions}
          onChangeDriveIntegrationId={setDriveIntegrationId}
        />
      )}
    </div>
    </GsapPageWrapper>
  );
}

/* ─── Detail Modal Component ──────────────────────────── */
function TemplateDetailModal({
  template,
  onClose,
  onUse,
  creating,
  copiedDemo,
  onCopyDemo,
  knowledgeBaseId,
  knowledgeBaseOptions,
  onChangeKnowledgeBaseId,
  driveIntegrationId,
  driveOptions,
  onChangeDriveIntegrationId,
}: {
  template: AgentTemplate;
  onClose: () => void;
  onUse: () => void;
  creating: boolean;
  copiedDemo: boolean;
  onCopyDemo: (s: string) => void;
  knowledgeBaseId: number | null;
  knowledgeBaseOptions: Array<{ id: number; name: string }>;
  onChangeKnowledgeBaseId: (id: number | null) => void;
  driveIntegrationId: number | null;
  driveOptions: Array<{ id: number; name: string }>;
  onChangeDriveIntegrationId: (id: number | null) => void;
}) {
  const Icon = getIcon(template.icon);
  const cs = getColorStyles(template.color);
  const [showStressTests, setShowStressTests] = useState(false);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[var(--bg-primary)]/80 backdrop-blur-sm">
      <div
        className={cn(
          'w-full max-w-2xl max-h-[90vh] overflow-y-auto dash-modal rounded-2xl border shadow-2xl',
          cs.border
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className={cn('p-6 border-b', cs.border)}>
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-4">
              <div className={cn('w-14 h-14 rounded-xl flex items-center justify-center', cs.bg)}>
                <Icon size={26} className={cs.text} />
              </div>
              <div>
                <h2 className="text-xl font-bold text-[var(--text-primary)]">{template.name}</h2>
                <p className={cn('text-sm font-medium', cs.text)}>{template.tagline}</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg bg-[var(--bg-tertiary)] flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              <X size={16} />
            </button>
          </div>

          {/* Badges */}
          <div className="flex flex-wrap gap-2 mt-4">
            <span className={cn('px-2.5 py-1 rounded-lg text-xs font-medium border', cs.badge, cs.border)}>
              {template.mode === 'single_prompt' ? 'Single Prompt' : 'Conversation Flow'}
            </span>
            {template.inbound_ready && (
              <span className="px-2.5 py-1 rounded-lg text-xs font-medium bg-emerald-500/15 text-emerald-300 border border-emerald-500/20 flex items-center gap-1">
                <Phone size={10} /> Inbound Ready
              </span>
            )}
            {template.outbound_ready && (
              <span className="px-2.5 py-1 rounded-lg text-xs font-medium bg-amber-500/15 text-amber-300 border border-amber-500/20 flex items-center gap-1">
                <PhoneOutgoing size={10} /> Outbound Ready
              </span>
            )}
            <span className="px-2.5 py-1 rounded-lg text-xs font-medium bg-[var(--bg-tertiary)] text-[var(--text-muted)] border border-[var(--border-color)] flex items-center gap-1">
              <Clock size={10} /> {template.estimated_setup_time} setup
            </span>
          </div>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-6">
          {/* Description */}
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2 flex items-center gap-2">
              <Info size={14} className="text-[var(--text-muted)]" />
              About this template
            </h3>
            <p className="text-sm text-[var(--text-muted)] leading-relaxed">{template.description}</p>
          </div>

          {/* Features */}
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3 flex items-center gap-2">
              <Zap size={14} className="text-[var(--text-muted)]" />
              Key Features
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {template.features.map((f) => (
                <div key={f} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
                  <Check size={14} className="text-emerald-400 flex-shrink-0" />
                  <span className="text-sm text-[var(--text-secondary)]">{f}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Demo Script */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
                <Play size={14} className="text-[var(--text-muted)]" />
                Demo Script
              </h3>
              <button
                onClick={() => onCopyDemo(template.demo_script)}
                className="flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                {copiedDemo ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                {copiedDemo ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <div className="p-4 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
              <pre className="text-xs text-[var(--text-muted)] whitespace-pre-wrap font-mono leading-relaxed">
                {template.demo_script}
              </pre>
            </div>
            <p className="text-xs text-[var(--text-muted)] mt-2">
              Use this script when testing the agent to experience its full capabilities.
            </p>
          </div>

          {/* Stress Test Cases (Adversarial) */}
          {template.adversarial_test_cases && template.adversarial_test_cases.length > 0 && (
            <div className="rounded-xl bg-red-500/5 border border-red-500/20 overflow-hidden">
              <button
                onClick={() => setShowStressTests(!showStressTests)}
                className="w-full flex items-center justify-between p-4 text-left"
              >
                <h3 className="text-sm font-semibold text-red-300 flex items-center gap-2">
                  <FlaskConical size={14} className="text-red-400" />
                  Stress Test Cases
                  <span className="px-2 py-0.5 rounded-md text-xs bg-red-500/15 text-red-300 border border-red-500/20">
                    {template.adversarial_test_cases.length}
                  </span>
                </h3>
                <ChevronDown
                  size={16}
                  className={cn('text-red-400 transition-transform', showStressTests && 'rotate-180')}
                />
              </button>
              {showStressTests && (
                <div className="px-4 pb-4 space-y-2">
                  {template.adversarial_test_cases.map((tc, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-3 p-3 rounded-lg bg-red-500/5 border border-red-500/10"
                    >
                      <span className="flex-shrink-0 w-5 h-5 rounded-md bg-red-500/15 text-red-300 text-xs font-bold flex items-center justify-center">
                        {i + 1}
                      </span>
                      <p className="text-xs text-red-200/80 leading-relaxed">{tc}</p>
                    </div>
                  ))}
                  <p className="text-xs text-red-300/50 pt-1">
                    These prompts simulate adversarial inputs a CS professor would use to test agent robustness.
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Recommended Tools */}
          {template.recommended_tools.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2 flex items-center gap-2">
                <Wand2 size={14} className="text-[var(--text-muted)]" />
                Recommended Tools
              </h3>
              <div className="flex flex-wrap gap-2">
                {template.recommended_tools.map((tool) => (
                  <span key={tool} className="px-3 py-1 rounded-lg text-xs font-medium bg-violet-500/10 text-violet-300 border border-violet-500/20">
                    {tool}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Setup Notes */}
          {template.setup_notes && (
            <div className="p-4 rounded-xl bg-amber-500/5 border border-amber-500/20">
              <h3 className="text-sm font-semibold text-amber-300 mb-2 flex items-center gap-2">
                <Wand2 size={14} className="text-amber-400" />
                Quick Setup Guide
              </h3>
              <p className="text-xs text-amber-200/80 whitespace-pre-wrap leading-relaxed">
                {template.setup_notes}
              </p>
            </div>
          )}

          {/* Knowledge Base */}
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2 flex items-center gap-2">
              <BookOpen size={14} className="text-[var(--text-muted)]" />
              Knowledge Base
            </h3>
            <select
              value={knowledgeBaseId ?? ''}
              onChange={(e) => onChangeKnowledgeBaseId(e.target.value ? Number(e.target.value) : null)}
              disabled={knowledgeBaseOptions.length === 0}
              className="w-full px-3 py-2.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-violet-500/30 disabled:opacity-60"
            >
              <option value="">
                {knowledgeBaseOptions.length === 0 ? 'No knowledge bases available' : 'No knowledge base linked'}
              </option>
              {knowledgeBaseOptions.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))}
            </select>
            <p className="text-xs text-[var(--text-muted)] mt-2">
              Optional. Ground the template with an existing knowledge base when creating the agent.
            </p>
          </div>

          {/* Google Drive */}
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2 flex items-center gap-2">
              <svg className="text-[var(--text-muted)]" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12h20"/><path d="M2 12l5-5"/><path d="M2 12l5 5"/></svg>
              Google Drive
            </h3>
            <select
              value={driveIntegrationId ?? ''}
              onChange={(e) => onChangeDriveIntegrationId(e.target.value ? Number(e.target.value) : null)}
              disabled={driveOptions.length === 0}
              className="w-full px-3 py-2.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-violet-500/30 disabled:opacity-60"
            >
              <option value="">
                {driveOptions.length === 0 ? 'No Google Drive integrations connected' : 'No Google Drive linked'}
              </option>
              {driveOptions.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
            <p className="text-xs text-[var(--text-muted)] mt-2">
              Optional. Attach a Google Drive integration so the agent can search and reference documents during calls.
            </p>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="p-6 border-t border-[var(--border-color)] flex items-center justify-between">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-sm font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onUse}
            disabled={creating}
            className={cn(
              'flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold text-[var(--text-primary)] transition-all',
              'bg-violet-600 hover:bg-violet-500 shadow-lg shadow-violet-500/20',
              creating && 'opacity-60 cursor-not-allowed'
            )}
          >
            {creating ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                Creating Agent...
              </>
            ) : (
              <>
                <Wand2 size={16} />
                Use This Template
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

