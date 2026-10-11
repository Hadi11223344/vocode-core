'use client';

import { useParams } from 'next/navigation';
import AgentBuilder from '../../_components/agent-builder';

export default function EditAgentBuilderPage() {
  const { id } = useParams();
  const agentId = Number(id);
  return <AgentBuilder agentId={agentId} />;
}
