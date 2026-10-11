import {
  Bot,
  CalendarCheck,
  Headset,
  Home,
  Languages,
  MessageCircleHeart,
  Package,
  Phone,
  Stethoscope,
  TrendingUp,
  UtensilsCrossed,
  type LucideIcon,
} from 'lucide-react';

import { agents as agentsApi } from '@/lib/api';
import { TEMPLATE_LIBRARY } from './templates';

const ICON_MAP: Record<string, LucideIcon> = {
  Headset,
  TrendingUp,
  CalendarCheck,
  Phone,
  UtensilsCrossed,
  Stethoscope,
  Package,
  MessageCircleHeart,
  Home,
  Languages,
};

const FALLBACK_ICON = Bot;

const CATEGORY_LABELS: Record<string, string> = {
  support: 'Support',
  sales: 'Sales',
  healthcare: 'Healthcare',
  hospitality: 'Hospitality',
  ecommerce: 'E-Commerce',
  realestate: 'Real Estate',
  general: 'General',
};

export type BackendTemplate = Awaited<ReturnType<typeof agentsApi.templates>>['templates'][number];

export interface Template {
  id: string;
  slug: string;
  name: string;
  tagline: string;
  description: string;
  category: string;
  mode: 'single_prompt' | 'conversational_flow';
  icon: LucideIcon;
  color: string;
  demo_script: string;
  recommended_tools: string[];
  outbound_ready: boolean;
  inbound_ready: boolean;
  estimated_setup_time: string;
  features: string[];
  global_prompt: string;
  initial_message: string;
  llm_provider: string;
  llm_model: string;
  stt_provider: string;
  stt_language: string;
  tts_provider: string;
  tts_voice_id: string;
}

function readConfigString(config: Record<string, unknown> | undefined, key: string, fallback = ''): string {
  const value = config?.[key];
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function normalizeIcon(name: string): LucideIcon {
  return ICON_MAP[name] || FALLBACK_ICON;
}

function normalizeBackendTemplate(template: BackendTemplate): Template {
  const config = template.config ?? {};
  return {
    id: template.id,
    slug: template.slug,
    name: template.name,
    tagline: template.tagline,
    description: template.description,
    category: template.category,
    mode: template.mode === 'conversational_flow' ? 'conversational_flow' : 'single_prompt',
    icon: normalizeIcon(template.icon),
    color: template.color,
    demo_script: template.demo_script,
    recommended_tools: template.recommended_tools ?? [],
    outbound_ready: Boolean(template.outbound_ready),
    inbound_ready: Boolean(template.inbound_ready),
    estimated_setup_time: template.estimated_setup_time || '2 min',
    features: template.features ?? [],
    global_prompt: readConfigString(config, 'prompt_preamble'),
    initial_message: readConfigString(config, 'initial_message'),
    llm_provider: readConfigString(config, 'llm_provider', 'groq'),
    llm_model: readConfigString(config, 'llm_model', 'openai/gpt-oss-120b'),
    stt_provider: readConfigString(config, 'stt_provider', 'deepgram'),
    stt_language: readConfigString(config, 'stt_language', 'en-US'),
    tts_provider: readConfigString(config, 'tts_provider', 'deepgram'),
    tts_voice_id: readConfigString(config, 'tts_voice_id', 'aura-asteria-en'),
  };
}

function normalizeLegacyTemplate(template: (typeof TEMPLATE_LIBRARY)[number]): Template {
  const firstGreeting = template.nodes?.find((node) => node.type === 'welcome')?.prompt || '';
  return {
    id: template.id,
    slug: template.id,
    name: template.name,
    tagline: template.description,
    description: template.description,
    category: template.category,
    mode: template.mode,
    icon: template.icon,
    color: 'cyan',
    demo_script: firstGreeting || template.global_prompt,
    recommended_tools: [],
    outbound_ready: template.mode === 'conversational_flow',
    inbound_ready: true,
    estimated_setup_time: '2 min',
    features: [],
    global_prompt: template.global_prompt,
    initial_message: firstGreeting,
    llm_provider: template.llm_provider,
    llm_model: template.llm_model,
    stt_provider: 'deepgram',
    stt_language: template.language,
    tts_provider: 'deepgram',
    tts_voice_id: template.voice_name.toLowerCase().replace(/\s+/g, '-'),
  };
}

export function templateCategoryLabel(category: string): string {
  return CATEGORY_LABELS[category] || category.replace(/_/g, ' ').replace(/\b\w/g, (match) => match.toUpperCase());
}

export function buildTemplateCategories(templates: Template[]): Array<{ id: string; label: string }> {
  const categories: Array<{ id: string; label: string }> = [{ id: 'all', label: 'All Templates' }];
  const seen = new Set<string>();

  for (const template of templates) {
    if (!template.category || seen.has(template.category)) {
      continue;
    }
    seen.add(template.category);
    categories.push({ id: template.category, label: templateCategoryLabel(template.category) });
  }

  return categories;
}

export async function loadTemplates(params?: { category?: string; mode?: string; outbound?: boolean }): Promise<Template[]> {
  try {
    const response = await agentsApi.templates(params);
    return response.templates.map(normalizeBackendTemplate);
  } catch {
    let templates = TEMPLATE_LIBRARY.map(normalizeLegacyTemplate);
    if (params?.category) {
      templates = templates.filter((template) => template.category === params.category);
    }
    if (params?.mode) {
      templates = templates.filter((template) => template.mode === params.mode);
    }
    if (params?.outbound !== undefined) {
      templates = templates.filter((template) => template.outbound_ready === params.outbound);
    }
    return templates;
  }
}
