'use client';

import { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { usePerformance } from '@/lib/performance-context';

/* ─── Voice Orb with shader displacement ─────────────── */
function VoiceOrbMesh({ amplitude = 0 }: { amplitude?: number }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const matRef = useRef<THREE.MeshStandardMaterial>(null);

  const geo = useMemo(() => new THREE.IcosahedronGeometry(1.2, 6), []);

  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uAmplitude: { value: amplitude },
    uColor1: { value: new THREE.Color('#6366f1') },
    uColor2: { value: new THREE.Color('#a855f7') },
  }), [amplitude]);

  const frameCount = useRef(0);

  useFrame((state) => {
    if (!meshRef.current) return;
    const t = state.clock.elapsedTime;
    frameCount.current++;
    uniforms.uTime.value = t;
    uniforms.uAmplitude.value += (amplitude - uniforms.uAmplitude.value) * 0.1;

    meshRef.current.rotation.y = t * 0.15;
    meshRef.current.rotation.x = Math.sin(t * 0.2) * 0.1;

    // Vertex displacement
    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const y = pos.getY(i);
      const z = pos.getZ(i);
      const noise = Math.sin(x * 3 + t * 2) * Math.cos(y * 3 + t * 1.5) * Math.sin(z * 3 + t);
      const scale = 1 + noise * (0.05 + uniforms.uAmplitude.value * 0.15);
      pos.setXYZ(i, x * scale, y * scale, z * scale);
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
        ref={matRef}
        color="#6366f1"
        emissive="#4f46e5"
        emissiveIntensity={0.3}
        metalness={0.6}
        roughness={0.2}
        wireframe={false}
        transparent
        opacity={0.85}
      />
    </mesh>
  );
}

function WireframeOverlay() {
  const meshRef = useRef<THREE.Mesh>(null);
  const geo = useMemo(() => new THREE.IcosahedronGeometry(1.25, 3), []);

  useFrame((state) => {
    if (!meshRef.current) return;
    meshRef.current.rotation.y = state.clock.elapsedTime * 0.1;
    meshRef.current.rotation.x = -state.clock.elapsedTime * 0.08;
  });

  return (
    <mesh ref={meshRef} geometry={geo}>
      <meshBasicMaterial color="#818cf8" wireframe transparent opacity={0.15} />
    </mesh>
  );
}

function OrbScene({ amplitude }: { amplitude: number }) {
  return (
    <>
      <ambientLight intensity={0.4} />
      <pointLight position={[3, 3, 3]} intensity={0.8} color="#6366f1" />
      <pointLight position={[-3, -2, 2]} intensity={0.4} color="#a855f7" />
      <VoiceOrbMesh amplitude={amplitude} />
      <WireframeOverlay />
    </>
  );
}

export default function VoiceOrb({ amplitude = 0, height = 200 }: { amplitude?: number; height?: number }) {
  const { quality } = usePerformance();
  if (quality === 'off') return null;

  return (
    <div style={{ width: '100%', height }}>
      <Canvas camera={{ position: [0, 0, 4], fov: 50 }} dpr={quality === 'high' ? [1, 2] as [number, number] : 1} gl={{ powerPreference: 'high-performance' }}>
        <OrbScene amplitude={amplitude} />
      </Canvas>
    </div>
  );
}
