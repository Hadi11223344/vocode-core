'use client';

import { memo, useEffect, useMemo } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  Panel,
  Node,
  Edge,
  Connection,
  useReactFlow,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { nodeTypes } from './WorkflowNodes';

interface WorkflowCanvasProps {
  nodes: Node[];
  edges: Edge[];
  onNodesChange: (changes: any[]) => void;
  onEdgesChange: (changes: any[]) => void;
  onConnect: (connection: Connection) => void;
  onNodeClick: (_: React.MouseEvent, node: Node) => void;
  onEdgeClick: (_: React.MouseEvent, edge: Edge) => void;
  onPaneClick: () => void;
  isValidConnection?: (connection: Connection | Edge) => boolean;
  invalidNodeIds?: Set<string>;
  children?: React.ReactNode;
}

const WorkflowCanvas = memo(function WorkflowCanvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onNodeClick,
  onEdgeClick,
  onPaneClick,
  isValidConnection,
  invalidNodeIds,
  children,
}: WorkflowCanvasProps) {
  const { fitView } = useReactFlow();
  const displayNodes = useMemo(
    () =>
      nodes.map(node => {
        if (!invalidNodeIds?.has(node.id)) return node;
        return {
          ...node,
          className: `${node.className || ''} ring-2 ring-red-500 ring-offset-2 ring-offset-[var(--bg-primary)]`.trim(),
        };
      }),
    [nodes, invalidNodeIds]
  );

  useEffect(() => {
    if (nodes.length === 0) return;
    const frame = requestAnimationFrame(() => {
      fitView({ padding: 0.2, duration: 250 });
    });
    return () => cancelAnimationFrame(frame);
  }, [fitView, nodes.length]);

  return (
    <ReactFlow
      nodes={displayNodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onNodeClick={onNodeClick}
      onEdgeClick={onEdgeClick}
      onPaneClick={onPaneClick}
      nodeTypes={nodeTypes}
      fitView
      deleteKeyCode={null}
      isValidConnection={isValidConnection}
      edgesFocusable={true}
      className="bg-[var(--bg-primary)]"
      defaultEdgeOptions={{
        animated: true,
        style: { stroke: '#6366f1', strokeWidth: 2 },
      }}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#2a2a3a" />
      <Controls
        className="!bg-[var(--bg-secondary)] !border-[var(--border-color)] !rounded-lg [&>button]:!bg-[var(--bg-secondary)] [&>button]:!border-[var(--border-color)] [&>button]:!text-[var(--text-secondary)] [&>button:hover]:!bg-[var(--bg-tertiary)]"
      />
      <MiniMap
        nodeColor={() => '#6366f1'}
        maskColor="rgba(10, 10, 15, 0.7)"
        className="!bg-[var(--bg-secondary)] !border-[var(--border-color)] !rounded-lg"
      />
      {children && <Panel position="top-left" className="!m-0">{children}</Panel>}
    </ReactFlow>
  );
});

export default WorkflowCanvas;
