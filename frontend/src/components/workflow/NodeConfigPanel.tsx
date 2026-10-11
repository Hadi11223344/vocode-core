'use client';

import { Node } from 'reactflow';
import { X, Trash2 } from 'lucide-react';
import { NODE_TYPES_CONFIG, NodeType } from './WorkflowNodes';
import { Integration } from '@/lib/types';
import { useState, useEffect, useRef } from 'react';
import { useToast } from '@/components/ui/toast';
import { apiKeys } from '@/lib/api';
import { IntegrationHelpButton } from '@/components/integrations/IntegrationHelpButton';
import { CONFIG_REGISTRY } from './node-configs/registry';
import { NODE_TYPE_TO_INTEGRATION, NodeConfigProps, PARAMETER_TEMPLATES } from './node-configs/types';
import { TemplateVarsReference } from './node-configs/shared';

interface NodeConfigPanelProps {
  node: Node | null;
  integrations: Integration[];
  onUpdate: (nodeId: string, data: Record<string, unknown>) => void;
  onDelete: (nodeId: string) => void;
  onClose: () => void;
}



export default function NodeConfigPanel({ node, integrations, onUpdate, onDelete, onClose }: NodeConfigPanelProps) {
  const { success, apiError } = useToast();

  // Keep a ref to the latest node so updateConfig/updateParam always read
  // current data, avoiding stale-closure bugs when multiple fields are
  // edited in rapid succession before React re-renders.
  const nodeRef = useRef(node);
  nodeRef.current = node;

  const nodeType = (node?.data.nodeType as NodeType) || 'webhook';
  const config = NODE_TYPES_CONFIG[nodeType];
  const Icon = config?.icon;

  // A1: For 'action' nodes, infer the real integration type from config.integration_type
  // so integration dropdown and action list work correctly.
  const nodeConfigPreview = (node?.data.config as Record<string, unknown>) || {};
  const effectiveNodeType: string = nodeType === 'action' && nodeConfigPreview.integration_type
    ? (nodeConfigPreview.integration_type as string)
    : nodeType;

  // Platform SMTP status for send_email nodes
  const [platformEmailReady, setPlatformEmailReady] = useState<boolean | null>(null);
  useEffect(() => {
    if (nodeType !== 'send_email') return;
    apiKeys.platformStatus()
      .then((data) => setPlatformEmailReady(!!data.platform_keys?.email))
      .catch(() => setPlatformEmailReady(false));
  }, [nodeType]);

  if (!node) return null;

  const updateData = (key: string, value: unknown) => {
    const n = nodeRef.current;
    if (!n) return;
    onUpdate(n.id, { ...n.data, [key]: value });
  };

  const updateConfig = (key: string, value: unknown) => {
    const n = nodeRef.current;
    if (!n) return;
    const cfg = { ...((n.data.config as Record<string, unknown>) || {}) };
    cfg[key] = value;
    onUpdate(n.id, { ...n.data, config: cfg });
  };

  const updateParam = (paramKey: string, paramValue: string) => {
    const n = nodeRef.current;
    if (!n) return;
    const params = { ...((n.data.params as Record<string, string>) || {}) };
    params[paramKey] = paramValue;
    onUpdate(n.id, { ...n.data, params });
  };

  const integrationServiceType = NODE_TYPE_TO_INTEGRATION[effectiveNodeType as NodeType] || effectiveNodeType;
  const matchingIntegrations = integrations.filter(
    i => i.service_type === integrationServiceType && i.is_active,
  );

  const nodeConfig = nodeConfigPreview;
  const parameterTemplates = PARAMETER_TEMPLATES[nodeType as NodeType] || [];

  // A1: Resolve the effective action from node.data.action or config.action (template fallback)
  const effectiveAction: string = (node.data.action as string) || (nodeConfig.action as string) || '';

  // Registry-based config component dispatch
  const ConfigComponent = CONFIG_REGISTRY[nodeType];
  const configProps: NodeConfigProps = {
    node,
    nodeConfig,
    updateConfig,
    updateData,
    updateParam,
    integrations,
    matchingIntegrations,
    effectiveNodeType,
    effectiveAction,
    parameterTemplates,
    platformEmailReady,
  };

  const parseJsonIfNeeded = (value: unknown, fieldName: string) => {
    if (value == null || value === '') return null;
    if (typeof value !== 'string') return value;
    try {
      return JSON.parse(value);
    } catch {
      throw new Error(`${fieldName} must be valid JSON`);
    }
  };

  const handleTestNode = () => {
    try {
      switch (nodeType) {
        case 'trigger': {
          const triggerPhrases = String(node.data.triggerPhrases || '').split('\n').map((s) => s.trim()).filter(Boolean);
          if (triggerPhrases.length === 0) throw new Error('Add at least one trigger phrase.');
          success('Node Ready', `${triggerPhrases.length} trigger phrase${triggerPhrases.length === 1 ? '' : 's'} configured.`);
          return;
        }
        case 'conversation': {
          const prompt = String(nodeConfig.prompt || '').trim();
          if (!prompt) throw new Error('Conversation prompt is required.');
          success('Node Ready', 'Conversation prompt looks good.');
          return;
        }
        case 'transfer_call': {
          const transferNumber = String(nodeConfig.transfer_number || nodeConfig.transfer_to || '').trim();
          if (!transferNumber) throw new Error('Transfer number is required.');
          success('Node Ready', `Will transfer to ${transferNumber}.`);
          return;
        }
        case 'knowledge_base': {
          const query = String(nodeConfig.query || '').trim();
          if (!query) throw new Error('Search query is required.');
          success('Node Ready', 'Knowledge base query is valid.');
          return;
        }
        case 'mcp_tool': {
          const serverUrl = String(nodeConfig.server_url || '').trim();
          if (!serverUrl) throw new Error('MCP server URL is required.');
          const toolName = String(nodeConfig.tool_name || '').trim();
          if (serverUrl.includes('drivemcp.googleapis.com') && !toolName) {
            throw new Error('Choose a Drive tool or leave the tool blank for auto-discovery.');
          }
          parseJsonIfNeeded(nodeConfig.parameters, 'Tool parameters');
          success('Node Ready', 'MCP tool configuration is valid.');
          return;
        }
        case 'api_request':
        case 'custom_api': {
          const url = String(nodeConfig.url || '').trim();
          if (!url) throw new Error('Request URL is required.');
          parseJsonIfNeeded(nodeConfig.headers, 'Headers');
          parseJsonIfNeeded(nodeConfig.body, 'Request body');
          parseJsonIfNeeded(nodeConfig.response_mappings, 'Response mappings');
          success('Node Ready', 'API request configuration is valid.');
          return;
        }
        case 'condition': {
          const expression = String(nodeConfig.expression || '').trim();
          if (!expression) throw new Error('Condition expression is required.');
          success('Node Ready', 'Condition expression is valid.');
          return;
        }
        case 'llm_process': {
          const prompt = String(nodeConfig.prompt || '').trim();
          if (!prompt) throw new Error('Processing prompt is required.');
          success('Node Ready', 'LLM process prompt is valid.');
          return;
        }
        case 'delay': {
          const delaySeconds = Number(nodeConfig.delay_seconds || 0);
          if (delaySeconds <= 0) throw new Error('Delay duration must be at least 1 second.');
          if (delaySeconds > 300) throw new Error('Delay duration cannot exceed 300 seconds.');
          success('Node Ready', `Delay set to ${delaySeconds}s.`);
          return;
        }
        case 'notification': {
          const message = String(nodeConfig.message || '').trim();
          if (!message) throw new Error('Notification message is required.');
          success('Node Ready', 'Notification configuration is valid.');
          return;
        }
        default:
          success('Node Ready', 'Node configuration looks valid.');
      }
    } catch (err) {
      apiError(err, 'Node test failed');
    }
  };

  return (
    <div className="w-80 bg-[var(--bg-secondary)] border-l border-[var(--border-color)] flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-color)]">
        <div className="flex items-center gap-2">
          {Icon && <Icon size={16} className={config?.headerColor?.split(' ').find((c: string) => c.startsWith('text-')) || 'text-brand-400'} />}
          <h3 className="text-sm font-semibold">{config?.label || 'Node'} Config</h3>
        </div>
        <div className="flex items-center gap-2">
          {NODE_TYPE_TO_INTEGRATION[effectiveNodeType as NodeType] && (
            <IntegrationHelpButton
              typeId={NODE_TYPE_TO_INTEGRATION[effectiveNodeType as NodeType]}
              size="sm"
              title="Learn more about this integration"
            />
          )}
          <button
            onClick={handleTestNode}
            aria-label="Test node configuration"
            className="px-2.5 py-1 text-[10px] font-medium rounded-md border border-brand-500/30 bg-brand-500/10 text-brand-400 hover:bg-brand-500/20 transition-colors"
          >
            Test Node
          </button>
          <button
            onClick={onClose}
            aria-label="Close node configuration panel"
            className="text-[var(--text-muted)] hover:text-white"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Label (all nodes) */}
        <div>
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Label</label>
          <input
            type="text"
            value={(node.data.label as string) || ''}
            onChange={e => updateData('label', e.target.value)}
            className="w-full input-base"
            placeholder="Node label..."
          />
        </div>

        {/* Description (all nodes) */}
        <div>
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Description</label>
          <textarea
            value={(node.data.description as string) || ''}
            onChange={e => updateData('description', e.target.value)}
            rows={2}
            className="w-full input-base resize-none"
            placeholder="What this step does..."
          />
        </div>

        {/* ═══ Node-type-specific config (dispatched via registry) ═══ */}
        {ConfigComponent && <ConfigComponent {...configProps} />}

        <TemplateVarsReference />
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-[var(--border-color)]">
        <button
          onClick={() => onDelete(node.id)}
          aria-label="Delete node"
          className="flex items-center gap-2 w-full px-3 py-2 text-red-400 hover:bg-red-500/10 rounded-lg text-sm transition-colors"
        >
          <Trash2 size={14} />
          Delete Node
        </button>
      </div>
    </div>
  );
}
