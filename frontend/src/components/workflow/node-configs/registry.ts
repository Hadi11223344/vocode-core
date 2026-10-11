import React from 'react';
import { NodeType } from '../WorkflowNodes';
import { NodeConfigProps } from './types';
import ConversationConfig from './ConversationConfig';
import SendEmailConfig from './SendEmailConfig';
import McpToolConfig from './McpToolConfig';
import ApiRequestConfig from './ApiRequestConfig';
import IntegrationConfig from './IntegrationConfig';
import TriggerConfig from './TriggerConfig';
import TransferCallConfig from './TransferCallConfig';
import SendSmsConfig from './SendSmsConfig';
import KnowledgeBaseConfig from './KnowledgeBaseConfig';
import EndCallConfig from './EndCallConfig';
import VoicemailDetectConfig from './VoicemailDetectConfig';
import WebhookConfig from './WebhookConfig';
import ConditionConfig from './ConditionConfig';
import SlotValidatorConfig from './SlotValidatorConfig';
import DelayConfig from './DelayConfig';
import LlmProcessConfig from './LlmProcessConfig';
import NotificationConfig from './NotificationConfig';
import NoteConfig from './NoteConfig';
import SubagentConfig from './SubagentConfig';
import ExtractVariableConfig from './ExtractVariableConfig';

const INTEGRATION_NODE_TYPES: NodeType[] = [
  'google_calendar', 'google_sheets', 'cal_com', 'calendly',
  'salesforce', 'pipedrive', 'gohighlevel', 'zendesk', 'intercom', 'freshdesk',
  'stripe', 'shopify', 'whatsapp_cloud', 'discord', 'microsoft_teams',
  'notion', 'airtable', 'make', 'jira', 'linear', 'action',
];

const integrationEntries: Partial<Record<NodeType, React.FC<NodeConfigProps>>> = Object.fromEntries(
  INTEGRATION_NODE_TYPES.map((nt) => [nt, IntegrationConfig])
);

export const CONFIG_REGISTRY: Partial<Record<NodeType, React.FC<NodeConfigProps>>> = {
  conversation: ConversationConfig,
  send_email: SendEmailConfig,
  mcp_tool: McpToolConfig,
  api_request: ApiRequestConfig,
  custom_api: ApiRequestConfig,
  trigger: TriggerConfig,
  transfer_call: TransferCallConfig,
  send_sms: SendSmsConfig,
  knowledge_base: KnowledgeBaseConfig,
  end_call: EndCallConfig,
  voicemail_detect: VoicemailDetectConfig,
  webhook: WebhookConfig,
  condition: ConditionConfig,
  slot_validator: SlotValidatorConfig,
  delay: DelayConfig,
  llm_process: LlmProcessConfig,
  notification: NotificationConfig,
  note: NoteConfig,
  subagent: SubagentConfig,
  extract_variable: ExtractVariableConfig,
  ...integrationEntries,
};
