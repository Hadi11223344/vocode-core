import { Node } from 'reactflow';
import { Integration } from '@/lib/types';
import { NodeType } from '../WorkflowNodes';

export interface NodeConfigProps {
  node: Node;
  nodeConfig: Record<string, unknown>;
  updateConfig: (key: string, value: unknown) => void;
  updateData: (key: string, value: unknown) => void;
  updateParam: (key: string, value: string) => void;
  integrations: Integration[];
  matchingIntegrations: Integration[];
  effectiveNodeType: string;
  effectiveAction: string;
  parameterTemplates: Array<{ label: string; value: string }>;
  platformEmailReady?: boolean | null;
}

export const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];

export const TEMPLATE_VARS = [
  { var: '{{caller_name}}', desc: 'Caller name' },
  { var: '{{caller_phone}}', desc: 'Caller phone number' },
  { var: '{{transcript}}', desc: 'Full call transcript' },
  { var: '{{agent_name}}', desc: 'Agent name' },
  { var: '{{call_duration}}', desc: 'Call duration' },
  { var: '{{next_business_day}}', desc: 'Next business day' },
  { var: '{{current_date}}', desc: 'Current date' },
  { var: '{{current_time}}', desc: 'Current time' },
  { var: '{{issue_type}}', desc: 'Detected issue type' },
  { var: '{{caller_email}}', desc: 'Caller email' },
  { var: '{{patient_name}}', desc: 'Patient name (extracted)' },
  { var: '{{preferred_date}}', desc: 'Preferred appointment date' },
  { var: '{{preferred_time}}', desc: 'Preferred appointment time' },
  { var: '{{preferred_dentist}}', desc: 'Preferred dentist' },
  { var: '{{service_requested}}', desc: 'Requested dental service' },
  { var: '{{insurance_provider}}', desc: 'Insurance provider' },
  { var: '{{is_new_patient}}', desc: 'New or existing patient' },
  { var: '{{is_emergency}}', desc: 'Emergency flag' },
  { var: '{{visit_type}}', desc: 'Visit type/reason' },
];

export const PARAMETER_TEMPLATES: Partial<Record<NodeType, Array<{ label: string; value: string }>>> = {
  mcp_tool: [
    { label: 'Drive Search', value: '{\n  "query": "{{caller_name}} invoice"\n}' },
    { label: 'Read File', value: '{\n  "file_id": "{{file_id}}"\n}' },
    { label: 'Recent Files', value: '{\n  "limit": 5\n}' },
  ],
  api_request: [
    { label: 'Caller Lookup', value: '{\n  "phone": "{{caller_phone}}"\n}' },
    { label: 'Transcript Payload', value: '{\n  "transcript": "{{transcript}}"\n}' },
  ],
  custom_api: [
    { label: 'Caller Lookup', value: '{\n  "phone": "{{caller_phone}}"\n}' },
    { label: 'Transcript Payload', value: '{\n  "transcript": "{{transcript}}"\n}' },
  ],
  knowledge_base: [
    { label: 'Issue Search', value: '{{issue_description}}' },
    { label: 'Transcript Search', value: '{{transcript}}' },
  ],
};

export const NODE_TYPE_TO_INTEGRATION: Partial<Record<NodeType, string>> = {
  google_calendar: 'google_calendar',
  google_sheets: 'google_sheets',
  cal_com: 'cal_com',
  calendly: 'calendly',
  salesforce: 'salesforce',
  pipedrive: 'pipedrive',
  gohighlevel: 'gohighlevel',
  zendesk: 'zendesk',
  intercom: 'intercom',
  freshdesk: 'freshdesk',
  stripe: 'stripe',
  shopify: 'shopify',
  whatsapp_cloud: 'whatsapp_cloud',
  discord: 'discord',
  microsoft_teams: 'microsoft_teams',
  notion: 'notion',
  airtable: 'airtable',
  make: 'make',
  jira: 'jira',
  linear: 'linear',
  send_email: 'email',
  send_sms: 'sms',
  webhook: 'webhook',
  api_request: 'webhook',
  custom_api: 'custom_api',
  mcp_tool: 'mcp',
  knowledge_base: 'knowledge_base',
  action: 'webhook',
};

export const INTEGRATION_ACTIONS: Record<string, { label: string; value: string }[]> = {
  google_calendar: [
    { label: 'Create Event', value: 'create_event' },
    { label: 'List Events', value: 'list_events' },
    { label: 'Update Event', value: 'update_event' },
    { label: 'Delete Event', value: 'delete_event' },
    { label: 'Check Availability', value: 'check_availability' },
    { label: 'Book Appointment', value: 'book_appointment' },
  ],
  google_sheets: [
    { label: 'Append Row', value: 'append_row' },
    { label: 'Read Rows', value: 'read_rows' },
    { label: 'Update Row', value: 'update_row' },
    { label: 'Search Rows', value: 'search_rows' },
  ],
  cal_com: [
    { label: 'Get Availability', value: 'get_availability' },
    { label: 'Create Booking', value: 'create_booking' },
    { label: 'Cancel Booking', value: 'cancel_booking' },
  ],
  knowledge_base: [
    { label: 'Retrieve Context', value: 'retrieve' },
    { label: 'Chunk Content', value: 'chunk_content' },
  ],
  calendly: [
    { label: 'Get Availability', value: 'get_availability' },
    { label: 'Create Invite Link', value: 'create_invite' },
    { label: 'Cancel Event', value: 'cancel_event' },
    { label: 'List Events', value: 'list_events' },
  ],
  salesforce: [
    { label: 'Create Lead', value: 'create_lead' },
    { label: 'Update Lead', value: 'update_lead' },
    { label: 'Create Contact', value: 'create_contact' },
    { label: 'Create Opportunity', value: 'create_opportunity' },
    { label: 'Search Records', value: 'search_records' },
    { label: 'Get Record', value: 'get_record' },
  ],
  pipedrive: [
    { label: 'Create Person', value: 'create_person' },
    { label: 'Create Deal', value: 'create_deal' },
    { label: 'Update Deal', value: 'update_deal' },
    { label: 'Add Note', value: 'add_note' },
    { label: 'Search Persons', value: 'search_persons' },
  ],
  gohighlevel: [
    { label: 'Create Contact', value: 'create_contact' },
    { label: 'Update Contact', value: 'update_contact' },
    { label: 'Create Opportunity', value: 'create_opportunity' },
    { label: 'Add Tag', value: 'add_tag' },
    { label: 'Create Task', value: 'create_task' },
  ],
  zendesk: [
    { label: 'Create Ticket', value: 'create_ticket' },
    { label: 'Update Ticket', value: 'update_ticket' },
    { label: 'Add Comment', value: 'add_comment' },
    { label: 'Search Tickets', value: 'search_tickets' },
    { label: 'Get Ticket', value: 'get_ticket' },
  ],
  intercom: [
    { label: 'Create Contact', value: 'create_contact' },
    { label: 'Send Message', value: 'send_message' },
    { label: 'Create Conversation', value: 'create_conversation' },
    { label: 'Add Tag', value: 'add_tag' },
    { label: 'Search Contacts', value: 'search_contacts' },
  ],
  freshdesk: [
    { label: 'Create Ticket', value: 'create_ticket' },
    { label: 'Update Ticket', value: 'update_ticket' },
    { label: 'Add Note', value: 'add_note' },
    { label: 'Get Ticket', value: 'get_ticket' },
    { label: 'Search Tickets', value: 'search_tickets' },
  ],
  stripe: [
    { label: 'Create Payment Link', value: 'create_payment_link' },
    { label: 'Create Invoice', value: 'create_invoice' },
    { label: 'List Invoices', value: 'list_invoices' },
    { label: 'Create Customer', value: 'create_customer' },
    { label: 'Check Payment Status', value: 'check_payment_status' },
  ],
  shopify: [
    { label: 'Get Order Status', value: 'get_order' },
    { label: 'Search Orders', value: 'search_orders' },
    { label: 'Get Product Info', value: 'get_product' },
    { label: 'Get Customer', value: 'get_customer' },
    { label: 'Search Products', value: 'search_products' },
  ],
  whatsapp_cloud: [
    { label: 'Send Message', value: 'send_message' },
    { label: 'Send Template', value: 'send_template' },
  ],
  discord: [
    { label: 'Send Message', value: 'send_message' },
    { label: 'Send Embed', value: 'send_embed' },
  ],
  microsoft_teams: [
    { label: 'Send Message', value: 'send_message' },
    { label: 'Send Card', value: 'send_card' },
  ],
  notion: [
    { label: 'Create Page', value: 'create_page' },
    { label: 'Update Page', value: 'update_page' },
    { label: 'Query Database', value: 'query_database' },
    { label: 'Append Block', value: 'append_block' },
  ],
  airtable: [
    { label: 'Create Record', value: 'create_record' },
    { label: 'Update Record', value: 'update_record' },
    { label: 'Search Records', value: 'search_records' },
    { label: 'List Records', value: 'list_records' },
  ],
  make: [
    { label: 'Trigger Scenario', value: 'trigger_scenario' },
  ],
  jira: [
    { label: 'Create Issue', value: 'create_issue' },
    { label: 'Update Issue', value: 'update_issue' },
    { label: 'Add Comment', value: 'add_comment' },
    { label: 'Transition Issue', value: 'transition_issue' },
    { label: 'Search Issues', value: 'search_issues' },
  ],
  linear: [
    { label: 'Create Issue', value: 'create_issue' },
    { label: 'Update Issue', value: 'update_issue' },
    { label: 'Add Comment', value: 'add_comment' },
    { label: 'Search Issues', value: 'search_issues' },
  ],
};
