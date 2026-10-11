"use client";

import { cn } from "@/lib/utils";
import { MessageSquare, Zap, Calendar, Phone, Stethoscope, Sparkles, Search, BookOpen, Megaphone, HeartPulse, ShoppingCart, Loader2, Headset, TrendingUp, CalendarCheck, UtensilsCrossed, Package, MessageCircleHeart, Home, Languages, ShieldCheck, DollarSign, Utensils, Briefcase, BarChart3, Users, GraduationCap, Smile } from "lucide-react";
import { CreateAgentRequest } from "@/lib/types";
import { useState, useEffect, useMemo } from "react";
import { agents as agentsApi } from "@/lib/api";

interface AgentPreset {
  id: string;
  title: string;
  subtitle: string;
  icon: React.ElementType;
  color: string;
  data: Partial<CreateAgentRequest>;
  tools_config?: string[];
}

const PRESETS: AgentPreset[] = [
  {
    id: "support",
    title: "Customer Support",
    subtitle: "Friendly support agent that resolves issues",
    icon: MessageSquare,
    color: "text-cyan-400 bg-cyan-400/10 border-cyan-400/20",
    data: {
      name: "Customer Support Agent",
      prompt_preamble:
        "You are a friendly and professional customer support agent. Your goal is to help callers resolve their issues quickly and efficiently. Listen carefully to their problem, ask clarifying questions when needed, and provide clear solutions. If you cannot resolve the issue, offer to escalate to a human agent. Always maintain a calm and empathetic tone.",
      initial_message: "Thank you for calling! My name is Alex, how can I help you today?",
      temperature: 0.5,
      max_tokens: 256,
      end_on_goodbye: true,
      interrupt_sensitivity: "high",
      filler_audio_enabled: true,
    },
    tools_config: ["read_sheet", "append_sheet", "send_email"],
  },
  {
    id: "sales",
    title: "Sales Representative",
    subtitle: "Persuasive agent that qualifies and converts leads",
    icon: Zap,
    color: "text-amber-400 bg-amber-400/10 border-amber-400/20",
    data: {
      name: "Sales Agent",
      prompt_preamble:
        "You are an enthusiastic and knowledgeable sales representative. Your goal is to understand the caller's needs, present relevant solutions, and guide them toward making a purchase decision. Be persuasive but not pushy. Ask qualifying questions to understand their budget, timeline, and requirements. Always highlight value and benefits rather than just features.",
      initial_message: "Hi there! Thanks for your interest. I'd love to learn about what you're looking for so I can find the perfect solution for you.",
      temperature: 0.7,
      max_tokens: 300,
      end_on_goodbye: true,
      interrupt_sensitivity: "low",
      filler_audio_enabled: true,
    },
    tools_config: ["check_calendar", "book_appointment", "send_email"],
  },
  {
    id: "scheduler",
    title: "Appointment Scheduler",
    subtitle: "Books and manages appointments smoothly",
    icon: Calendar,
    color: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
    data: {
      name: "Appointment Scheduler",
      prompt_preamble:
        "You are a professional appointment scheduling assistant. Help callers book, reschedule, or cancel appointments. Collect their name, preferred date and time, reason for the appointment, and contact information. Confirm all details before finalizing. Be efficient and organized while maintaining a warm, helpful tone.",
      initial_message: "Hello! I'd be happy to help you schedule an appointment. Would you like to book a new appointment or manage an existing one?",
      temperature: 0.3,
      max_tokens: 200,
      end_on_goodbye: true,
      interrupt_sensitivity: "high",
      filler_audio_enabled: false,
    },
    tools_config: ["check_calendar", "book_appointment", "send_sms", "send_email"],
  },
  {
    id: "receptionist",
    title: "Virtual Receptionist",
    subtitle: "Greets callers and routes them to the right place",
    icon: Phone,
    color: "text-purple-400 bg-purple-400/10 border-purple-400/20",
    data: {
      name: "Virtual Receptionist",
      prompt_preamble:
        "You are a professional virtual receptionist. Greet callers warmly and determine the purpose of their call. Route them to the appropriate department or person. If the person they want to reach is unavailable, take a message including their name, phone number, and reason for calling. Be polite, professional, and efficient.",
      initial_message: "Good day! Thank you for calling. How may I direct your call?",
      temperature: 0.4,
      max_tokens: 200,
      end_on_goodbye: true,
      interrupt_sensitivity: "high",
      filler_audio_enabled: false,
    },
    tools_config: ["send_email", "send_sms", "recall_document"],
  },
  {
    id: "healthcare_faq",
    title: "Healthcare FAQ & Scheduler",
    subtitle: "Answers patient questions and books appointments",
    icon: Stethoscope,
    color: "text-rose-400 bg-rose-400/10 border-rose-400/20",
    data: {
      name: "Healthcare FAQ Agent",
      prompt_preamble:
        "You are a friendly receptionist at a healthcare practice. Help callers with questions about services, hours, and insurance. Use calendar tools to book, reschedule, or cancel appointments. Collect name, reason for visit, preferred date/time, and contact info when booking. Escalate distressed callers, medical diagnosis requests, billing disputes, or legal matters to a human immediately.",
      initial_message: "Thank you for calling. How can I help you today?",
      temperature: 0.3,
      max_tokens: 300,
      end_on_goodbye: true,
      interrupt_sensitivity: "low",
      filler_audio_enabled: true,
    },
    tools_config: ["check_calendar", "book_appointment", "send_sms"],
  },
  {
    id: "umt_admission",
    title: "UMT Admission Counselor",
    subtitle: "Guides students on programs, merit, and scholarships. Upload knowledge_base/umt_faq.md to KB.",
    icon: BookOpen,
    color: "text-sky-400 bg-sky-400/10 border-sky-400/20",
    data: {
      name: "UMT Admission Counselor",
      prompt_preamble:
        "You are an official admissions counselor at the University of Management and Technology (UMT) in Lahore, Pakistan. You help prospective students and parents with detailed, accurate information about undergraduate and graduate programs, admission requirements, merit criteria, fee structures, scholarships, campus facilities, and career prospects. Use the knowledge base to answer specific questions about programs like BBA, BS CS, BS AI, BS SE, MBA, MS, and PhD. Collect the caller's name, city, program of interest, and Intermediate marks so you can assess scholarship eligibility and log the inquiry into the connected spreadsheet. Speak warmly and use a mix of English and Urdu phrases where natural for Lahore-based students. Always confirm the caller's email or phone number before sending a follow-up. If asked about topics unrelated to UMT admissions (politics, religion, personal advice), politely deflect and return to admissions. End the call if the caller is abusive or persistently off-topic after two warnings.",
      initial_message: "Assalam-o-Alaikum! Thank you for calling UMT Admissions. My name is Sara — I'm here to help you with programs, fees, and scholarships. What can I assist you with today?",
      temperature: 0.4,
      max_tokens: 350,
      end_on_goodbye: true,
      interrupt_sensitivity: "low",
      filler_audio_enabled: true,
    },
    tools_config: ["read_sheet", "append_sheet", "send_sms", "send_email"],
  },
  {
    id: "umt_outreach",
    title: "UMT Outreach & Sales",
    subtitle: "Proactive counselor qualifying leads and driving admissions. Upload knowledge_base/umt_outreach.md to KB.",
    icon: Megaphone,
    color: "text-indigo-400 bg-indigo-400/10 border-indigo-400/20",
    data: {
      name: "UMT Outreach Counselor",
      prompt_preamble:
        "You are a proactive admissions outreach counselor for UMT Lahore. Your role is to call prospective students who showed interest in UMT and guide them toward applying. Be persuasive but ethical — never pressure or mislead. Highlight UMT's value: HEC top-10 ranking, affordable fees (40-60% lower than LUMS/FAST), generous scholarships starting at 75% marks, and 85% placement rate. Ask qualifying questions: program interest, Intermediate marks, city, budget concerns, other universities applied to. Calculate and explain scholarship eligibility on the call. If the student is ready, encourage them to apply at admissions.umt.edu.pk. Offer to schedule a campus visit or virtual session. Log every lead detail into the connected spreadsheet. Always confirm the phone number before sending follow-up messages. If the student is clearly uninterested after two follow-up attempts, thank them and close politely. Do not disparage other universities.",
      initial_message: "Hi! This is Bilal from UMT Admissions. I saw you were interested in our programs — I'd love to answer any questions and help you figure out the best fit. Do you have a few minutes?",
      temperature: 0.6,
      max_tokens: 350,
      end_on_goodbye: true,
      interrupt_sensitivity: "low",
      filler_audio_enabled: true,
    },
    tools_config: ["read_sheet", "append_sheet", "check_calendar", "book_appointment", "send_sms", "send_email"],
  },
  {
    id: "smilecare",
    title: "SmileCare Dental Receptionist",
    subtitle: "Full-stack dental receptionist — inbound & outbound. Upload knowledge_base/dental_clinic.txt to KB and link it.",
    icon: HeartPulse,
    color: "text-teal-400 bg-teal-400/10 border-teal-400/20",
    data: {
      name: "SmileCare Dental Receptionist",
      prompt_preamble:
        "You are Sara, a receptionist at SmileCare Dental Clinic on MM Alam Road, Gulberg III, Lahore. You answer inbound calls from patients (booking, rescheduling, emergency triage, FAQs) and make outbound calls (appointment reminders, post-procedure follow-ups, reactivation). Use the knowledge base for all facts: 6 dentists with specialties, services & pricing, insurance (EFU, Adamjee, Jubilee, TPL), discounts (family 10%, student 15%, senior 20%, referral free consultation), clinic hours, cancellation policy (4 hours, PKR 500 fee), and emergency protocols. For emergencies (severe pain with swelling, knocked-out tooth, bleeding, jaw injury, abscess with fever), direct to 24/7 emergency line 0300-1234567. Speak naturally with contractions and fillers. Keep responses to 1-3 sentences. One question at a time. No bullet points or markdown. Match caller tone. You are NOT a dentist — never diagnose. Log patients to Sheets with incremental capture. Confirm appointments via email. Mention discounts proactively. Verify insurance before booking.",
      initial_message: "Hello! Welcome to SmileCare Dental. How can I help you today?",
      temperature: 0.5,
      max_tokens: 350,
      end_on_goodbye: true,
      interrupt_sensitivity: "high",
      filler_audio_enabled: true,
    },
    tools_config: ["read_sheet", "append_sheet", "check_calendar", "book_appointment", "send_email", "recall_document"],
  },
  {
    id: "ecommerce_sales",
    title: "StyleHub.pk Sales Agent",
    subtitle: "Voice shopping assistant for fashion orders. Upload knowledge_base/ecommerce_catalog.md to KB.",
    icon: ShoppingCart,
    color: "text-pink-400 bg-pink-400/10 border-pink-400/20",
    data: {
      name: "StyleHub Sales Agent",
      prompt_preamble:
        "You are a friendly voice shopping assistant for StyleHub.pk, an online fashion store based in Lahore. You help customers browse products, check availability, place orders, and answer questions about delivery, returns, and payments. Use the connected spreadsheet to look up product inventory, prices, and sizes. Ask for the product ID or describe what they're looking for. Collect order details: product ID, size, color, quantity, full name, delivery address, phone number, and payment preference (COD or online). Calculate the total including delivery charges (free above PKR 3,000, otherwise PKR 250). Confirm all details before finalizing the order. After confirmation, log the order into the spreadsheet and send an order confirmation via email with the order number and estimated delivery date. Offer upsells naturally: suggest matching dupattas for suits, or a waistcoat for kurta orders. Be helpful and enthusiastic but not pushy. If the caller is not shopping or becomes abusive, politely end the call after one warning.",
      initial_message: "Hello and welcome to StyleHub.pk! This is Amina — your personal shopping assistant. What are you looking for today? We have beautiful lawn suits, kurtas, and Western wear for the whole family!",
      temperature: 0.6,
      max_tokens: 350,
      end_on_goodbye: true,
      interrupt_sensitivity: "low",
      filler_audio_enabled: true,
    },
  },
];

interface TemplateGalleryProps {
  onSelectPreset: (preset: AgentPreset) => void;
  onStartFromScratch: () => void;
}

const ICON_MAP: Record<string, React.ElementType> = {
  MessageSquare, Zap, Calendar, Phone, Stethoscope, BookOpen, Megaphone, HeartPulse, ShoppingCart, Sparkles,
  Headset, TrendingUp, CalendarCheck, UtensilsCrossed, Package, MessageCircleHeart, Home, Languages,
  ShieldCheck, DollarSign, Utensils, Briefcase, BarChart3, Users, GraduationCap, Smile,
};

const COLOR_MAP: Record<string, string> = {
  cyan: "text-cyan-400 bg-cyan-400/10 border-cyan-400/20",
  amber: "text-amber-400 bg-amber-400/10 border-amber-400/20",
  emerald: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
  purple: "text-purple-400 bg-purple-400/10 border-purple-400/20",
  violet: "text-violet-400 bg-violet-400/10 border-violet-400/20",
  rose: "text-rose-400 bg-rose-400/10 border-rose-400/20",
  sky: "text-sky-400 bg-sky-400/10 border-sky-400/20",
  indigo: "text-indigo-400 bg-indigo-400/10 border-indigo-400/20",
  teal: "text-teal-400 bg-teal-400/10 border-teal-400/20",
  pink: "text-pink-400 bg-pink-400/10 border-pink-400/20",
  orange: "text-orange-400 bg-orange-400/10 border-orange-400/20",
  blue: "text-blue-400 bg-blue-400/10 border-blue-400/20",
  brand: "text-brand-400 bg-brand-400/10 border-brand-400/20",
};

export default function TemplateGallery({ onSelectPreset, onStartFromScratch }: TemplateGalleryProps) {
  const [search, setSearch] = useState("");
  const [backendPresets, setBackendPresets] = useState<AgentPreset[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await agentsApi.templates();
        if (cancelled) return;
        const mapped: AgentPreset[] = data.templates
          .filter((t) => t.mode === "single_prompt")
          .map((t) => ({
            id: t.id,
            title: t.name,
            subtitle: t.tagline,
            icon: ICON_MAP[t.icon] || Sparkles,
            color: COLOR_MAP[t.color] || COLOR_MAP.brand,
            data: t.config as Partial<CreateAgentRequest>,
            tools_config: t.recommended_tools,
          }));
        setBackendPresets(mapped);
      } catch {
        // Fall back to hardcoded presets only
      } finally {
        if (!cancelled) setLoadingTemplates(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const allPresets = useMemo(() => {
    const merged = [...backendPresets];
    for (const p of PRESETS) {
      if (!backendPresets.some((bp) => bp.id === p.id)) {
        merged.push(p);
      }
    }
    return merged;
  }, [backendPresets]);

  const filtered = allPresets.filter((p) =>
    p.title.toLowerCase().includes(search.toLowerCase()) ||
    p.subtitle.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="max-w-5xl mx-auto space-y-8 animate-in fade-in duration-300">
      <div className="text-center space-y-3">
        <h1 className="text-2xl font-bold tracking-tight">Choose a Template</h1>
        <p className="text-sm text-[var(--text-muted)]">
          Start with a pre-configured agent, or build from scratch.
        </p>
        <div className="relative max-w-md mx-auto">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search templates..."
            className="w-full input-base text-sm pl-9"
          />
        </div>
      </div>

      {loadingTemplates && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={20} className="animate-spin text-brand-400" />
        </div>
      )}

      {!loadingTemplates && filtered.length === 0 && (
        <div className="text-center py-12 text-sm text-[var(--text-muted)]">
          No templates match &quot;{search}&quot;.
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map((preset) => {
          const Icon = preset.icon;
          return (
            <button
              key={preset.id}
              onClick={() => onSelectPreset(preset)}
              className="dash-card p-5 text-left hover:border-brand-500/40 transition-all group"
            >
              <div className="flex items-start gap-4">
                <div className={cn("p-3 rounded-xl border shrink-0", preset.color)}>
                  <Icon size={22} />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold group-hover:text-brand-400 transition-colors">
                    {preset.title}
                  </h3>
                  <p className="text-xs text-[var(--text-muted)] mt-1">{preset.subtitle}</p>
                  <div className="flex items-center gap-2 mt-3">
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
                      temp: {preset.data.temperature}
                    </span>
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
                      {preset.data.max_tokens} tokens
                    </span>
                  </div>
                </div>
              </div>
            </button>
          );
        })}

        <button
          onClick={onStartFromScratch}
          className="dash-card p-5 text-left hover:border-brand-500/40 transition-all group border-dashed"
        >
          <div className="flex items-start gap-4">
            <div className="p-3 rounded-xl border shrink-0 text-[var(--text-muted)] bg-[var(--bg-tertiary)]">
              <Sparkles size={22} />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="font-semibold group-hover:text-brand-400 transition-colors">
                Start from Scratch
              </h3>
              <p className="text-xs text-[var(--text-muted)] mt-1">
                Build a custom agent with your own prompt and settings.
              </p>
            </div>
          </div>
        </button>
      </div>
    </div>
  );
}

export { PRESETS };
export type { AgentPreset };
