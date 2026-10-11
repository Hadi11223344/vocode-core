'use client';

import { NodeConfigProps } from './types';
import { DriveFileBrowser } from './shared';

export default function McpToolConfig({ nodeConfig, updateConfig, integrations }: NodeConfigProps) {
  return (
    <>
      {/* Quick Preset Selector */}
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Server Preset</label>
        <select
          value={
            (nodeConfig.server_url as string)?.includes('drivemcp.googleapis.com') ? 'google_drive'
              : (nodeConfig.server_url as string)?.includes('calendarmcp.googleapis.com') ? 'google_calendar_mcp'
              : (nodeConfig.server_url as string)?.includes('gmailmcp.googleapis.com') ? 'google_gmail_mcp'
              : 'custom'
          }
          onChange={e => {
            const presets: Record<string, string> = {
              google_drive: 'https://drivemcp.googleapis.com/mcp/v1',
              google_calendar_mcp: 'https://calendarmcp.googleapis.com/mcp/v1',
              google_gmail_mcp: 'https://gmailmcp.googleapis.com/mcp/v1',
              custom: '',
            };
            updateConfig('server_url', presets[e.target.value] || '');
            if (e.target.value !== 'custom') {
              updateConfig('auth_token', '');
            }
          }}
          className="w-full input-base"
        >
          <option value="custom">Custom MCP Server</option>
          <option value="google_drive">📁 Google Drive MCP</option>
          <option value="google_calendar_mcp">📅 Google Calendar MCP</option>
          <option value="google_gmail_mcp">📧 Gmail MCP</option>
        </select>
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">MCP Server URL</label>
        <input
          type="text"
          value={(nodeConfig.server_url as string) || ''}
          onChange={e => updateConfig('server_url', e.target.value)}
          className="w-full input-base font-mono"
          placeholder="https://mcp.example.com"
        />
      </div>
      {/* Show OAuth badge for Google MCP hosts, otherwise show auth token field */}
      {(nodeConfig.server_url as string)?.includes('.googleapis.com') ? (
        <div className="flex items-center gap-2 p-2.5 rounded-lg bg-green-500/10 border border-green-500/20">
          <span className="text-green-400 text-xs font-medium">🔐 OAuth</span>
          <span className="text-[11px] text-[var(--text-secondary)]">
            Auth handled via your connected Google account — no token needed.
          </span>
        </div>
      ) : (
        <div>
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Auth Token (Optional)</label>
          <input
            type="password"
            value={(nodeConfig.auth_token as string) || ''}
            onChange={e => updateConfig('auth_token', e.target.value)}
            className="w-full input-base"
            placeholder="Bearer token..."
          />
        </div>
      )}
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Tool Name</label>
        {(nodeConfig.server_url as string)?.includes('drivemcp.googleapis.com') ? (
          <>
            <select
              value={(nodeConfig.tool_name as string) || ''}
              onChange={e => updateConfig('tool_name', e.target.value)}
              className="w-full input-base"
            >
              <option value="">All tools (auto-discover)</option>
              <option value="search_files">🔍 Search Files</option>
              <option value="read_file_content">📖 Read File Content</option>
              <option value="create_file">📝 Create File</option>
              <option value="copy_file">📋 Copy File</option>
              <option value="get_file_metadata">ℹ️ Get File Metadata</option>
              <option value="get_file_permissions">🔒 Get File Permissions</option>
              <option value="list_recent_files">🕐 List Recent Files</option>
              <option value="download_file_content">⬇️ Download File Content</option>
            </select>
            <p className="text-[10px] text-[var(--text-muted)] mt-1">
              Select a specific Drive tool or leave empty to let the agent choose dynamically.
            </p>
          </>
        ) : (
          <>
            <input
              type="text"
              value={(nodeConfig.tool_name as string) || ''}
              onChange={e => updateConfig('tool_name', e.target.value)}
              className="w-full input-base font-mono"
              placeholder="e.g. get_customer_info"
            />
            <p className="text-[10px] text-[var(--text-muted)] mt-1">Leave blank to expose all server tools to the agent dynamically.</p>
          </>
        )}
      </div>
      {/* Drive File Browser */}
      {(nodeConfig.server_url as string)?.includes('drivemcp.googleapis.com') && (
        <DriveFileBrowser
          integrations={integrations}
          onSelect={(fileId: string, _fileName: string) => {
            updateConfig('tool_name', 'read_file_content');
            updateConfig('parameters', JSON.stringify({ file_id: fileId }, null, 2));
          }}
        />
      )}
      {(nodeConfig.tool_name as string) && (
        <div>
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Tool Parameters (JSON)</label>
          <textarea
            value={(nodeConfig.parameters as string) || ''}
            onChange={e => updateConfig('parameters', e.target.value)}
            rows={3}
            className="w-full input-base resize-none font-mono"
            placeholder={'{\n  "query": "{{caller_name}} invoice"\n}'}
          />
        </div>
      )}
    </>
  );
}
