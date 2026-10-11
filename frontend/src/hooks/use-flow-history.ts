'use client';

import { useState, useCallback, useRef } from 'react';
import { Node, Edge } from 'reactflow';

interface HistoryState {
  nodes: Node[];
  edges: Edge[];
}

interface HistoryData {
  stack: HistoryState[];
  index: number;
}

export function useFlowHistory(initialNodes: Node[] = [], initialEdges: Edge[] = []) {
  const [data, setData] = useState<HistoryData>({
    stack: [{ nodes: initialNodes, edges: initialEdges }],
    index: 0,
  });

  const dataRef = useRef(data);
  dataRef.current = data;

  const canUndo = data.index > 0;
  const canRedo = data.index < data.stack.length - 1;

  const push = useCallback((nodes: Node[], edges: Edge[]) => {
    setData(prev => {
      const nextStack = prev.stack.slice(0, prev.index + 1);
      nextStack.push({ nodes, edges });
      if (nextStack.length > 50) {
        nextStack.shift();
        return { stack: nextStack, index: 49 };
      }
      return { stack: nextStack, index: prev.index + 1 };
    });
  }, []);

  const undo = useCallback((): HistoryState | null => {
    const current = dataRef.current;
    if (current.index <= 0) return null;
    const newIndex = current.index - 1;
    setData(prev => ({ ...prev, index: newIndex }));
    return current.stack[newIndex] ?? null;
  }, []);

  const redo = useCallback((): HistoryState | null => {
    const current = dataRef.current;
    if (current.index >= current.stack.length - 1) return null;
    const newIndex = current.index + 1;
    setData(prev => ({ ...prev, index: newIndex }));
    return current.stack[newIndex] ?? null;
  }, []);

  return { push, undo, redo, canUndo, canRedo };
}
