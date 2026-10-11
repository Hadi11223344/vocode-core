'use client';

import { useRef, useMemo, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { usePerformance } from '@/lib/performance-context';

interface Donut3DData {
  label: string;
  value: number;
  color: string;
}

function DonutSegment({ startAngle, endAngle, radius, color, index, hovered, setHovered }: {
  startAngle: number;
  endAngle: number;
  radius: number;
  color: string;
  index: number;
  hovered: number | null;
  setHovered: (i: number | null) => void;
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const tube = 0.35;

  const geometry = useMemo(() => {
    const shape = new THREE.Shape();
    const segments = 32;
    const angleSpan = endAngle - startAngle;
    const segSize = angleSpan / segments;

    // Outer arc
    for (let i = 0; i <= segments; i++) {
      const a = startAngle + segSize * i;
      const x = Math.cos(a) * radius;
      const y = Math.sin(a) * radius;
      if (i === 0) shape.moveTo(x, y);
      else shape.lineTo(x, y);
    }
    // Inner arc (reverse)
    for (let i = segments; i >= 0; i--) {
      const a = startAngle + segSize * i;
      const x = Math.cos(a) * (radius - tube);
      const y = Math.sin(a) * (radius - tube);
      shape.lineTo(x, y);
    }
    shape.closePath();

    const geo = new THREE.ExtrudeGeometry(shape, {
      depth: 0.3,
      bevelEnabled: true,
      bevelThickness: 0.05,
      bevelSize: 0.04,
      bevelSegments: 2,
    });
    return geo;
  }, [startAngle, endAngle, radius, tube]);

  useFrame(() => {
    if (!meshRef.current) return;
    const targetZ = hovered === index ? 0.3 : 0;
    meshRef.current.position.z += (targetZ - meshRef.current.position.z) * 0.15;
  });

  return (
    <mesh
      ref={meshRef}
      geometry={geometry}
      onPointerOver={(e) => { e.stopPropagation(); setHovered(index); }}
      onPointerOut={() => setHovered(null)}
    >
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={hovered === index ? 0.3 : 0.1}
        metalness={0.3}
        roughness={0.4}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

function Donut3DScene({ data }: { data: Donut3DData[] }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const groupRef = useRef<THREE.Group>(null);
  const total = data.reduce((sum, d) => sum + d.value, 0) || 1;
  const radius = 1.5;

  useFrame((state) => {
    if (!groupRef.current) return;
    groupRef.current.rotation.z = state.clock.elapsedTime * 0.1;
  });

  let currentAngle = 0;
  const segments = data.map((d, i) => {
    const angle = (d.value / total) * Math.PI * 2;
    const seg = (
      <DonutSegment
        key={i}
        startAngle={currentAngle}
        endAngle={currentAngle + angle}
        radius={radius}
        color={d.color}
        index={i}
        hovered={hovered}
        setHovered={setHovered}
      />
    );
    currentAngle += angle;
    return seg;
  });

  return (
    <>
      <ambientLight intensity={0.7} />
      <directionalLight position={[3, 5, 5]} intensity={0.8} />
      <directionalLight position={[-3, -2, 3]} intensity={0.3} color="#a855f7" />
      <group ref={groupRef} rotation={[-Math.PI / 2.5, 0, 0]}>
        {segments}
      </group>
    </>
  );
}

export default function Donut3D({ data, height = 200 }: { data: Donut3DData[]; height?: number }) {
  const { quality } = usePerformance();
  if (quality === 'off') return null;

  return (
    <div style={{ width: '100%', height }}>
      <Canvas camera={{ position: [0, 3, 4], fov: 50 }} dpr={quality === 'high' ? [1, 2] as [number, number] : 1} gl={{ powerPreference: 'high-performance' }}>
        <Donut3DScene data={data} />
      </Canvas>
    </div>
  );
}
