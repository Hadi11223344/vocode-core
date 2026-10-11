'use client';

import { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { usePerformance } from '@/lib/performance-context';

interface SentimentData {
  positive: number;
  neutral: number;
  negative: number;
  mixed: number;
}

function SentimentTerrain({ data }: { data: SentimentData }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const geo = useMemo(() => new THREE.SphereGeometry(1.3, 64, 48), []);

  const frameCount = useRef(0);

  useFrame((state) => {
    if (!meshRef.current) return;
    const t = state.clock.elapsedTime;
    frameCount.current++;
    meshRef.current.rotation.y = t * 0.08;

    const pos = geo.attributes.position;
    const total = data.positive + data.neutral + data.negative + data.mixed || 1;

    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const y = pos.getY(i);
      const z = pos.getZ(i);

      const lat = Math.asin(y / 1.3);
      const lon = Math.atan2(z, x);

      // Positive = peaks, negative = valleys
      const posInf = (data.positive / total) * Math.sin(lon * 3 + t * 0.5) * 0.15;
      const negInf = (data.negative / total) * Math.cos(lat * 4 + t * 0.3) * -0.12;
      const neutralInf = (data.neutral / total) * Math.sin(lat * 2 + lon * 2) * 0.04;
      const mixInf = (data.mixed / total) * Math.cos(lon * 5 + t * 0.4) * 0.06;

      const displacement = 1 + posInf + negInf + neutralInf + mixInf;
      pos.setXYZ(i, x * displacement, y * displacement, z * displacement);
    }
    pos.needsUpdate = true;
    // Recompute normals every 3rd frame to reduce CPU load
    if (frameCount.current % 3 === 0) {
      geo.computeVertexNormals();
    }
  });

  return (
    <mesh ref={meshRef} geometry={geo}>
      <meshStandardMaterial
        vertexColors
        emissive="#312e81"
        emissiveIntensity={0.15}
        metalness={0.5}
        roughness={0.3}
        wireframe={false}
        transparent
        opacity={0.9}
      />
    </mesh>
  );
}

function WireframeGlobe() {
  const meshRef = useRef<THREE.Mesh>(null);
  const geo = useMemo(() => new THREE.SphereGeometry(1.35, 32, 24), []);

  useFrame((state) => {
    if (!meshRef.current) return;
    meshRef.current.rotation.y = state.clock.elapsedTime * 0.06;
  });

  return (
    <mesh ref={meshRef} geometry={geo}>
      <meshBasicMaterial color="#818cf8" wireframe transparent opacity={0.1} />
    </mesh>
  );
}

function SentimentGlobeScene({ data }: { data: SentimentData }) {
  return (
    <>
      <ambientLight intensity={0.5} />
      <pointLight position={[4, 4, 4]} intensity={0.8} color="#6366f1" />
      <pointLight position={[-3, -2, -3]} intensity={0.4} color="#a855f7" />
      <SentimentTerrain data={data} />
      <WireframeGlobe />
    </>
  );
}

export default function SentimentGlobe({ data, height = 220 }: { data: SentimentData; height?: number }) {
  const { quality } = usePerformance();
  if (quality === 'off') return null;

  return (
    <div style={{ width: '100%', height }}>
      <Canvas camera={{ position: [0, 0, 4], fov: 50 }} dpr={quality === 'high' ? [1, 2] as [number, number] : 1} gl={{ powerPreference: 'high-performance' }}>
        <SentimentGlobeScene data={data} />
      </Canvas>
    </div>
  );
}
