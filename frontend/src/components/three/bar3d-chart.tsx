'use client';

import { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { usePerformance } from '@/lib/performance-context';

interface Bar3DData {
  label: string;
  value: number;
}

function Bar3D({ data, index, maxVal, hovered, setHovered }: {
  data: Bar3DData;
  index: number;
  maxVal: number;
  hovered: number | null;
  setHovered: (i: number | null) => void;
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const targetHeight = Math.max((data.value / maxVal) * 3, 0.05);
  const x = (index - (7 / 2)) * 0.6;

  useFrame((state) => {
    if (!meshRef.current) return;
    const t = state.clock.elapsedTime;
    const currentY = meshRef.current.scale.y;
    meshRef.current.scale.y += (targetHeight - currentY) * 0.1;

    if (hovered === index) {
      meshRef.current.position.y = 1.5 + Math.sin(t * 4) * 0.05;
    } else {
      meshRef.current.position.y = 1.5;
    }
  });

  return (
    <group position={[x, 0, 0]}>
      <mesh
        ref={meshRef}
        scale={[1, 1, 1]}
        onPointerOver={(e) => { e.stopPropagation(); setHovered(index); }}
        onPointerOut={() => setHovered(null)}
      >
        <boxGeometry args={[0.4, 1, 0.4]} />
        <meshStandardMaterial
          color={hovered === index ? '#818cf8' : '#6366f1'}
          emissive={hovered === index ? '#4f46e5' : '#312e81'}
          emissiveIntensity={hovered === index ? 0.4 : 0.2}
          transparent
          opacity={0.85}
        />
      </mesh>
      {/* Base */}
      <mesh position={[0, 0, 0]}>
        <boxGeometry args={[0.42, 0.05, 0.42]} />
        <meshStandardMaterial color="#1e1b4b" transparent opacity={0.5} />
      </mesh>
    </group>
  );
}

function Bar3DScene({ data }: { data: Bar3DData[] }) {
  const maxVal = Math.max(...data.map(d => d.value), 1);

  return (
    <>
      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 8, 5]} intensity={0.8} />
      <directionalLight position={[-5, 3, -5]} intensity={0.3} color="#a855f7" />
      <group position={[0, -1, 0]}>
        {data.map((d, i) => (
          <Bar3D key={i} data={d} index={i} maxVal={maxVal} hovered={null} setHovered={() => {}} />
        ))}
      </group>
    </>
  );
}

export default function Bar3DChart({ data, height = 200 }: { data: Bar3DData[]; height?: number }) {
  const { quality } = usePerformance();
  if (quality === 'off') return null;

  return (
    <div style={{ width: '100%', height }}>
      <Canvas camera={{ position: [0, 2, 6], fov: 50 }} dpr={quality === 'high' ? [1, 2] as [number, number] : 1} gl={{ powerPreference: 'high-performance' }}>
        <Bar3DScene data={data} />
      </Canvas>
    </div>
  );
}
