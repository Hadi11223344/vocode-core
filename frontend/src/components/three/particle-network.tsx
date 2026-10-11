'use client';

import { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { usePerformance } from '@/lib/performance-context';

interface CallNode {
  id: string;
  position: [number, number, number];
  color: string;
  pulse: boolean;
}

interface Connection {
  from: number;
  to: number;
}

function Node({ node, index }: { node: CallNode; index: number }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const ringRef = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (!meshRef.current || !ringRef.current) return;
    const t = state.clock.elapsedTime;
    meshRef.current.position.y = node.position[1] + Math.sin(t * 0.5 + index) * 0.1;

    if (node.pulse) {
      const s = 1 + Math.sin(t * 3) * 0.15;
      ringRef.current.scale.set(s, s, s);
      ringRef.current.rotation.z = t * 0.5;
    }
  });

  return (
    <group position={node.position}>
      <mesh ref={meshRef}>
        <sphereGeometry args={[0.12, 16, 16]} />
        <meshStandardMaterial
          color={node.color}
          emissive={node.color}
          emissiveIntensity={0.5}
          transparent
          opacity={0.9}
        />
      </mesh>
      {node.pulse && (
        <mesh ref={ringRef} rotation={[Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.18, 0.22, 32]} />
          <meshBasicMaterial color={node.color} transparent opacity={0.4} side={THREE.DoubleSide} />
        </mesh>
      )}
    </group>
  );
}

function ConnectionLine({ from, to }: { from: [number, number, number]; to: [number, number, number] }) {
  const geo = useMemo(() => {
    const start = new THREE.Vector3(...from);
    const end = new THREE.Vector3(...to);
    const mid = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
    mid.z += 0.5;
    const curve = new THREE.QuadraticBezierCurve3(start, mid, end);
    return new THREE.TubeGeometry(curve, 20, 0.015, 8, false);
  }, [from, to]);

  return (
    <mesh geometry={geo}>
      <meshBasicMaterial color="#6366f1" transparent opacity={0.2} />
    </mesh>
  );
}

function ParticleNetworkScene({ nodes, connections }: { nodes: CallNode[]; connections: Connection[] }) {
  const groupRef = useRef<THREE.Group>(null);

  useFrame((state) => {
    if (!groupRef.current) return;
    groupRef.current.rotation.y = state.clock.elapsedTime * 0.05;
  });

  return (
    <>
      <ambientLight intensity={0.5} />
      <pointLight position={[5, 5, 5]} intensity={0.5} />
      <group ref={groupRef}>
        {connections.map((conn, i) => (
          <ConnectionLine key={i} from={nodes[conn.from].position} to={nodes[conn.to].position} />
        ))}
        {nodes.map((node, i) => (
          <Node key={i} node={node} index={i} />
        ))}
      </group>
    </>
  );
}

export default function ParticleNetwork({ nodes, connections, height = 250 }: {
  nodes: CallNode[];
  connections: Connection[];
  height?: number;
}) {
  const { quality } = usePerformance();
  if (quality === 'off' || nodes.length === 0) return null;

  return (
    <div style={{ width: '100%', height }}>
      <Canvas camera={{ position: [0, 0, 6], fov: 55 }} dpr={quality === 'high' ? [1, 2] as [number, number] : 1} gl={{ powerPreference: 'high-performance' }}>
        <ParticleNetworkScene nodes={nodes} connections={connections} />
      </Canvas>
    </div>
  );
}
