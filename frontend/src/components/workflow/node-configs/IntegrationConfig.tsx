'use client';

import { NodeConfigProps, INTEGRATION_ACTIONS } from './types';

export default function IntegrationConfig({
  node,
  nodeConfig,
  updateData,
  updateParam,
  matchingIntegrations,
  effectiveNodeType,
  effectiveAction,
}: NodeConfigProps) {
  const nodeType = (node.data.nodeType as string) || '';
  const params = (node.data.params as Record<string, string>) || {};

  return (
    <>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Integration</label>
        {matchingIntegrations.length > 0 ? (
          <select
            value={(node.data.integrationId as string) || ''}
            onChange={e => updateData('integrationId', e.target.value)}
            className="w-full input-base"
          >
            <option value="">Select integration...</option>
            {matchingIntegrations.map(int => (
              <option key={int.id} value={String(int.id)}>{int.name}</option>
            ))}
          </select>
        ) : (
          <p className="text-xs text-amber-400 bg-amber-500/10 p-2 rounded-lg">
            No {(effectiveNodeType as string).replace(/_/g, ' ')} integrations configured. Add one in Settings &rarr; Integrations.
          </p>
        )}
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Action</label>
        <select
          value={(node.data.action as string) || (nodeConfig.action as string) || ''}
          onChange={e => updateData('action', e.target.value)}
          className="w-full input-base"
        >
          <option value="">Select action...</option>
          {(INTEGRATION_ACTIONS[effectiveNodeType] || []).map(a => (
            <option key={a.value} value={a.value}>{a.label}</option>
          ))}
        </select>
      </div>

      {/* Dynamic params based on action */}
      {effectiveAction === 'create_event' && (
        <>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Event Summary</label>
            <input
              type="text"
              value={params?.summary || ''}
              onChange={e => updateParam('summary', e.target.value)}
              className="w-full input-base"
              placeholder="Call follow-up with {{caller_name}}"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Date</label>
            <input
              type="text"
              value={params?.date || ''}
              onChange={e => updateParam('date', e.target.value)}
              className="w-full input-base"
              placeholder="{{next_business_day}}"
            />
          </div>
        </>
      )}
      {effectiveAction === 'check_availability' && (
        <>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Date</label>
            <input
              type="text"
              value={params?.date || ''}
              onChange={e => updateParam('date', e.target.value)}
              className="w-full input-base"
              placeholder="{{preferred_date}}"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Duration (minutes)</label>
            <input
              type="number"
              value={params?.duration_minutes || '30'}
              onChange={e => updateParam('duration_minutes', e.target.value)}
              className="w-full input-base"
              min={5}
              max={120}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Business Hours Start</label>
            <input
              type="text"
              value={params?.business_hours_start || '10:00'}
              onChange={e => updateParam('business_hours_start', e.target.value)}
              className="w-full input-base"
              placeholder="10:00"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Business Hours End</label>
            <input
              type="text"
              value={params?.business_hours_end || '21:00'}
              onChange={e => updateParam('business_hours_end', e.target.value)}
              className="w-full input-base"
              placeholder="21:00"
            />
          </div>
          <p className="text-[10px] text-[var(--text-muted)] mt-1">
            Checks available time slots on the given date within business hours.
          </p>
        </>
      )}
      {effectiveAction === 'book_appointment' && (
        <>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Date</label>
            <input
              type="text"
              value={params?.date || ''}
              onChange={e => updateParam('date', e.target.value)}
              className="w-full input-base"
              placeholder="{{preferred_date}}"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Time</label>
            <input
              type="text"
              value={params?.time || ''}
              onChange={e => updateParam('time', e.target.value)}
              className="w-full input-base"
              placeholder="{{preferred_time}}"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Purpose</label>
            <input
              type="text"
              value={params?.purpose || ''}
              onChange={e => updateParam('purpose', e.target.value)}
              className="w-full input-base"
              placeholder="{{service_requested}}"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Duration (minutes)</label>
            <input
              type="number"
              value={params?.duration_minutes || '30'}
              onChange={e => updateParam('duration_minutes', e.target.value)}
              className="w-full input-base"
              min={5}
              max={120}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Attendee Name</label>
            <input
              type="text"
              value={params?.attendee_name || ''}
              onChange={e => updateParam('attendee_name', e.target.value)}
              className="w-full input-base"
              placeholder="{{patient_name}}"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Attendee Phone</label>
            <input
              type="text"
              value={params?.attendee_phone || ''}
              onChange={e => updateParam('attendee_phone', e.target.value)}
              className="w-full input-base font-mono"
              placeholder="{{caller_phone}}"
            />
          </div>
          <p className="text-[10px] text-[var(--text-muted)] mt-1">
            Composite action: checks availability, creates a calendar event, and returns booking confirmation.
          </p>
        </>
      )}
      {effectiveAction === 'append_row' && (
        <div>
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Row Data (JSON)</label>
          <textarea
            value={params?.row_data || ''}
            onChange={e => updateParam('row_data', e.target.value)}
            rows={3}
            className="w-full input-base resize-none font-mono"
            placeholder={'["{{caller_name}}", "{{caller_phone}}", "{{current_date}}"]'}
          />
        </div>
      )}
      {effectiveAction === 'create_booking' && (
        <>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Attendee Name</label>
            <input
              type="text"
              value={params?.name || ''}
              onChange={e => updateParam('name', e.target.value)}
              className="w-full input-base"
              placeholder="{{caller_name}}"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Attendee Email</label>
            <input
              type="text"
              value={params?.email || ''}
              onChange={e => updateParam('email', e.target.value)}
              className="w-full input-base"
              placeholder="{{caller_email}}"
            />
          </div>
        </>
      )}

      {/* ── CRM: Create Lead / Contact / Opportunity ── */}
      {(effectiveAction === 'create_lead' || effectiveAction === 'create_contact' || effectiveAction === 'create_person') && (
        <>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Name</label>
            <input type="text" value={params?.name || ''} onChange={e => updateParam('name', e.target.value)} className="w-full input-base" placeholder="{{caller_name}}" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Phone</label>
            <input type="text" value={params?.phone || ''} onChange={e => updateParam('phone', e.target.value)} className="w-full input-base font-mono" placeholder="{{caller_phone}}" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Email</label>
            <input type="text" value={params?.email || ''} onChange={e => updateParam('email', e.target.value)} className="w-full input-base" placeholder="{{caller_email}}" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Source / Notes</label>
            <input type="text" value={params?.source || ''} onChange={e => updateParam('source', e.target.value)} className="w-full input-base" placeholder="VOIA AI Inbound Call" />
          </div>
        </>
      )}
      {(effectiveAction === 'create_deal' || effectiveAction === 'create_opportunity') && (
        <>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Deal / Opportunity Title</label>
            <input type="text" value={params?.title || ''} onChange={e => updateParam('title', e.target.value)} className="w-full input-base" placeholder="{{caller_name}} - Inbound Inquiry" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Value / Amount</label>
            <input type="text" value={params?.value || ''} onChange={e => updateParam('value', e.target.value)} className="w-full input-base font-mono" placeholder="0" />
          </div>
        </>
      )}

      {/* ── Support: Create Ticket ── */}
      {effectiveAction === 'create_ticket' && (
        <>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Subject</label>
            <input type="text" value={params?.subject || ''} onChange={e => updateParam('subject', e.target.value)} className="w-full input-base" placeholder="Call from {{caller_name}} - {{issue_type}}" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Description</label>
            <textarea value={params?.description || ''} onChange={e => updateParam('description', e.target.value)} rows={3} className="w-full input-base resize-none" placeholder="Summary of call: {{transcript}}" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Priority</label>
            <select value={params?.priority || 'medium'} onChange={e => updateParam('priority', e.target.value)} className="w-full input-base">
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
          </div>
        </>
      )}

      {/* ── Stripe: Payment ── */}
      {effectiveAction === 'create_payment_link' && (
        <>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Amount (cents)</label>
            <input type="text" value={params?.amount || ''} onChange={e => updateParam('amount', e.target.value)} className="w-full input-base font-mono" placeholder="5000" />
            <p className="text-[10px] text-[var(--text-muted)] mt-1">Amount in cents (e.g. 5000 = $50.00)</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Product Name</label>
            <input type="text" value={params?.product_name || ''} onChange={e => updateParam('product_name', e.target.value)} className="w-full input-base" placeholder="Service Fee" />
          </div>
        </>
      )}
      {effectiveAction === 'create_invoice' && (
        <>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Customer ID</label>
            <input type="text" value={params?.customer_id || ''} onChange={e => updateParam('customer_id', e.target.value)} className="w-full input-base font-mono" placeholder="cus_..." />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Description</label>
            <input type="text" value={params?.description || ''} onChange={e => updateParam('description', e.target.value)} className="w-full input-base" placeholder="Invoice for {{caller_name}}" />
          </div>
        </>
      )}

      {/* ── Shopify: Orders ── */}
      {(effectiveAction === 'get_order' || effectiveAction === 'search_orders') && effectiveNodeType === 'shopify' && (
        <div>
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">{effectiveAction === 'get_order' ? 'Order ID' : 'Search Query'}</label>
          <input type="text" value={params?.[effectiveAction === 'get_order' ? 'order_id' : 'query'] || ''} onChange={e => updateParam(effectiveAction === 'get_order' ? 'order_id' : 'query', e.target.value)} className="w-full input-base font-mono" placeholder={effectiveAction === 'get_order' ? '#1001' : '{{caller_name}}'} />
        </div>
      )}

      {/* ── Project: Create Issue (Jira / Linear) ── */}
      {effectiveAction === 'create_issue' && (
        <>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Title</label>
            <input type="text" value={params?.title || ''} onChange={e => updateParam('title', e.target.value)} className="w-full input-base" placeholder="Issue from call: {{caller_name}}" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Description</label>
            <textarea value={params?.description || ''} onChange={e => updateParam('description', e.target.value)} rows={3} className="w-full input-base resize-none" placeholder="{{transcript}}" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Priority</label>
            <select value={params?.priority || 'Medium'} onChange={e => updateParam('priority', e.target.value)} className="w-full input-base">
              <option value="Low">Low</option>
              <option value="Medium">Medium</option>
              <option value="High">High</option>
              <option value="Critical">Critical</option>
            </select>
          </div>
        </>
      )}

      {/* ── Communication: Send Message (WhatsApp, Discord, Teams, etc.) ── */}
      {effectiveAction === 'send_message' && (
        <div>
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Message</label>
          <textarea value={params?.message || ''} onChange={e => updateParam('message', e.target.value)} rows={3} className="w-full input-base resize-none" placeholder="New call from {{caller_name}} ({{caller_phone}}): {{transcript}}" />
        </div>
      )}

      {/* ── Productivity: Create Page / Record ── */}
      {(effectiveAction === 'create_page' || effectiveAction === 'create_record' || effectiveAction === 'add_to_database') && (
        <>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Title / Record Name</label>
            <input type="text" value={params?.title || ''} onChange={e => updateParam('title', e.target.value)} className="w-full input-base" placeholder="Call Notes - {{caller_name}}" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Content / Fields (JSON)</label>
            <textarea value={params?.content || ''} onChange={e => updateParam('content', e.target.value)} rows={3} className="w-full input-base resize-none font-mono" placeholder={'{"Name": "{{caller_name}}", "Phone": "{{caller_phone}}"}'} />
          </div>
        </>
      )}

      {/* ── Generic: Search / Query actions ── */}
      {(effectiveAction === 'search_records' || effectiveAction === 'search_tickets' || effectiveAction === 'search_contacts' || effectiveAction === 'search_issues' || effectiveAction === 'search') && (
        <div>
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Search Query</label>
          <input type="text" value={params?.query || ''} onChange={e => updateParam('query', e.target.value)} className="w-full input-base" placeholder="{{caller_name}} OR {{caller_phone}}" />
        </div>
      )}

      {/* ── Generic: Add Comment / Note ── */}
      {(effectiveAction === 'add_comment' || effectiveAction === 'add_note') && (
        <>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">{nodeType === 'jira' || nodeType === 'linear' ? 'Issue ID' : 'Record ID'}</label>
            <input type="text" value={params?.issue_key || params?.id || ''} onChange={e => updateParam(nodeType === 'jira' ? 'issue_key' : nodeType === 'linear' ? 'issue_id' : 'id', e.target.value)} className="w-full input-base font-mono" placeholder="PROJ-123" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Comment / Note</label>
            <textarea value={params?.comment || params?.note || ''} onChange={e => updateParam(effectiveAction === 'add_note' ? 'note' : 'comment', e.target.value)} rows={3} className="w-full input-base resize-none" placeholder="AI call summary: {{transcript}}" />
          </div>
        </>
      )}

      {/* ── Automation: Make / Zapier webhook trigger ── */}
      {(effectiveAction === 'trigger_scenario' || effectiveAction === 'send_data') && (
        <div>
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Payload (JSON)</label>
          <textarea value={params?.body || ''} onChange={e => updateParam('body', e.target.value)} rows={4} className="w-full input-base resize-none font-mono" placeholder={'{\n  "caller": "{{caller_name}}",\n  "phone": "{{caller_phone}}",\n  "summary": "{{transcript}}"\n}'} />
        </div>
      )}
    </>
  );
}
