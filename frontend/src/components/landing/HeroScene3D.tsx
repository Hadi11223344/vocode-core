'use client';

import { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Float, Sparkles, MeshDistortMaterial, Icosahedron, Torus } from '@react-three/drei';
import * as THREE from 'three';

function VoiceWaveRings() {
  const groupRef = useRef<THREE.Group>(null);

  useFrame((state) => {
    if (!groupRef.current) return;
    const t = state.clock.getElapsedTime();
    groupRef.current.rotation.z = t * 0.1;
    groupRef.current.rotation.x = Math.sin(t * 0.3) * 0.15;
  });

  const rings = useMemo(() => {
    const items = [];
    for (let i = 0; i < 5; i++) {
      const radius = 1 + i * 0.4;
      const tubeRadius = Math.max(0.01, 0.02 - i * 0.003);
      items.push({
        radius,
        tubeRadius,
        opacity: 0.8 - i * 0.15,
        color: i % 2 === 0 ? '#6366f1' : '#8b5cf6',
        speed: 0.5 + i * 0.2,
      });
    }
    return items;
  }, []);

  return (
    <group ref={groupRef}>
      {rings.map((ring, i) => (
        <Torus
          key={i}
          args={[ring.radius, ring.tubeRadius, 16, 100]}
          rotation={[Math.PI / 2 + i * 0.1, 0, 0]}
        >
          <meshStandardMaterial
            color={ring.color}
            transparent
            opacity={ring.opacity}
            emissive={ring.color}
            emissiveIntensity={0.5}
          />
        </Torus>
      ))}
    </group>
  );
}

function PulsingCore() {
  const meshRef = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (!meshRef.current) return;
    const t = state.clock.getElapsedTime();
    const scale = 1 + Math.sin(t * 2) * 0.05;
    meshRef.current.scale.set(scale, scale, scale);
  });

  return (
    <Icosahedron ref={meshRef} args={[0.6, 4]}>
      <MeshDistortMaterial
        color="#6366f1"
        emissive="#4f46e5"
        emissiveIntensity={0.6}
        distort={0.3}
        speed={2}
        roughness={0.2}
        metalness={0.8}
      />
    </Icosahedron>
  );
}

function FloatingShape({
  position,
  color,
  shape = 'icosahedron',
}: {
  position: [number, number, number];
  color: string;
  shape?: 'icosahedron' | 'torus';
}) {
  return (
    <Float speed={2} rotationIntensity={1} floatIntensity={1.5}>
      {shape === 'icosahedron' ? (
        <mesh position={position}>
          <icosahedronGeometry args={[0.25, 0]} />
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={0.3}
            roughness={0.3}
            metalness={0.7}
            wireframe
          />
        </mesh>
      ) : (
        <mesh position={position} rotation={[Math.PI / 4, 0, 0]}>
          <torusGeometry args={[0.2, 0.06, 8, 24]} />
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={0.3}
            roughness={0.3}
            metalness={0.7}
            wireframe
          />
        </mesh>
      )}
    </Float>
  );
}

export default function HeroScene3D() {
  return (
    <Canvas
      camera={{ position: [0, 0, 5], fov: 50 }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true }}
      style={{ background: 'transparent' }}
    >
      <ambientLight intensity={0.3} />
      <pointLight position={[5, 5, 5]} intensity={0.8} color="#6366f1" />
      <pointLight position={[-5, -3, 3]} intensity={0.6} color="#8b5cf6" />
      <pointLight position={[0, 5, -5]} intensity={0.4} color="#06b6d4" />

      <group position={[0, 0, 0]}>
        <PulsingCore />
        <VoiceWaveRings />
      </group>

      <FloatingShape position={[-2, 1.5, -1]} color="#8b5cf6" shape="icosahedron" />
      <FloatingShape position={[2.2, -1.2, -0.5]} color="#06b6d4" shape="torus" />
      <FloatingShape position={[1.8, 1.8, -1.5]} color="#a855f7" shape="icosahedron" />
      <FloatingShape position={[-2.2, -1.5, -0.8]} color="#6366f1" shape="torus" />

      <Sparkles
        count={80}
        scale={8}
        size={2}
        speed={0.3}
        opacity={0.4}
        color="#818cf8"
      />
    </Canvas>
  );
}
