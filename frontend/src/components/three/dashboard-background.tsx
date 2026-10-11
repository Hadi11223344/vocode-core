'use client';

import { useRef, useMemo, useState, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { usePerformance } from '@/lib/performance-context';

/* ─── Particle Field ──────────────────────────────────── */
function ParticleField({ count, isLight }: { count: number; isLight: boolean }) {
  const pointsRef = useRef<THREE.Points>(null);
  const mouseRef = useRef({ x: 0, y: 0 });
  const { viewport } = useThree();

  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      arr[i * 3] = (Math.random() - 0.5) * 20;
      arr[i * 3 + 1] = (Math.random() - 0.5) * 12;
      arr[i * 3 + 2] = (Math.random() - 0.5) * 10 - 2;
    }
    return arr;
  }, [count]);

  const colors = useMemo(() => {
    const arr = new Float32Array(count * 3);
    const c1 = new THREE.Color(isLight ? '#4f46e5' : '#6366f1');
    const c2 = new THREE.Color(isLight ? '#7c3aed' : '#a855f7');
    for (let i = 0; i < count; i++) {
      const mix = Math.random();
      const c = c1.clone().lerp(c2, mix);
      arr[i * 3] = c.r;
      arr[i * 3 + 1] = c.g;
      arr[i * 3 + 2] = c.b;
    }
    return arr;
  }, [count, isLight]);

  useFrame((state) => {
    if (!pointsRef.current) return;
    const t = state.clock.elapsedTime;
    pointsRef.current.rotation.y = t * 0.03;
    pointsRef.current.rotation.x = Math.sin(t * 0.1) * 0.05;

    // Mouse parallax
    mouseRef.current.x += (state.mouse.x - mouseRef.current.x) * 0.05;
    mouseRef.current.y += (state.mouse.y - mouseRef.current.y) * 0.05;
    pointsRef.current.position.x = mouseRef.current.x * 0.5;
    pointsRef.current.position.y = mouseRef.current.y * 0.3;
  });

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[colors, 3]} />
      </bufferGeometry>
      <pointsMaterial
        size={0.04}
        vertexColors
        transparent
        opacity={isLight ? 0.18 : 0.12}
        sizeAttenuation
        blending={isLight ? THREE.NormalBlending : THREE.AdditiveBlending}
        depthWrite={false}
      />
    </points>
  );
}

/* ─── Morphing Wave Plane ─────────────────────────────── */
function WavePlane({ isLight }: { isLight: boolean }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const geo = useMemo(() => new THREE.PlaneGeometry(30, 18, 60, 36), []);

  useFrame((state) => {
    if (!meshRef.current) return;
    const t = state.clock.elapsedTime;
    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const y = pos.getY(i);
      const z = Math.sin(x * 0.3 + t * 0.5) * 0.4 + Math.cos(y * 0.3 + t * 0.3) * 0.4;
      pos.setZ(i, z);
    }
    pos.needsUpdate = true;
    meshRef.current.rotation.z = t * 0.02;
  });

  return (
    <mesh ref={meshRef} geometry={geo} position={[0, 0, -4]}>
      <meshBasicMaterial
        color={isLight ? '#4f46e5' : '#6366f1'}
        wireframe
        transparent
        opacity={isLight ? 0.03 : 0.03}
      />
    </mesh>
  );
}

/* ─── Floating Geometric Shapes ───────────────────────── */
function FloatingShapes({ isLight }: { isLight: boolean }) {
  const groupRef = useRef<THREE.Group>(null);

  const shapes = useMemo(() => {
    const items: { pos: [number, number, number]; scale: number; type: 'ico' | 'octa' | 'tetra'; speed: number }[] = [];
    const types: ('ico' | 'octa' | 'tetra')[] = ['ico', 'octa', 'tetra'];
    for (let i = 0; i < 8; i++) {
      items.push({
        pos: [(Math.random() - 0.5) * 16, (Math.random() - 0.5) * 10, (Math.random() - 0.5) * 6 - 1],
        scale: 0.15 + Math.random() * 0.3,
        type: types[Math.floor(Math.random() * types.length)],
        speed: 0.2 + Math.random() * 0.4,
      });
    }
    return items;
  }, []);

  useFrame((state) => {
    if (!groupRef.current) return;
    const t = state.clock.elapsedTime;
    groupRef.current.children.forEach((child, i) => {
      child.rotation.x = t * shapes[i].speed * 0.5;
      child.rotation.y = t * shapes[i].speed;
      child.position.y += Math.sin(t * shapes[i].speed + i) * 0.002;
    });
  });

  return (
    <group ref={groupRef}>
      {shapes.map((s, i) => (
        <mesh key={i} position={s.pos} scale={s.scale}>
          {s.type === 'ico' && <icosahedronGeometry args={[1, 0]} />}
          {s.type === 'octa' && <octahedronGeometry args={[1, 0]} />}
          {s.type === 'tetra' && <tetrahedronGeometry args={[1, 0]} />}
          <meshBasicMaterial color={isLight ? '#6366f1' : '#818cf8'} wireframe transparent opacity={isLight ? 0.04 : 0.03} />
        </mesh>
      ))}
    </group>
  );
}

/* ─── Main Background Scene ───────────────────────────── */
function Scene({ particleCount, isLight }: { particleCount: number; isLight: boolean }) {
  return (
    <>
      <ambientLight intensity={0.5} />
      <ParticleField count={particleCount} isLight={isLight} />
      <WavePlane isLight={isLight} />
      <FloatingShapes isLight={isLight} />
    </>
  );
}

/* ─── Exported Component ──────────────────────────────── */
const NO_BG_ROUTES = [
  '/dashboard/settings',
  '/dashboard/knowledge-base',
  '/dashboard/integrations',
  '/dashboard/billing',
  '/dashboard/numbers',
  '/dashboard/reviews',
  '/dashboard/playground',
  '/dashboard/agents',
  '/dashboard/workflows',
  '/dashboard/campaigns',
  '/dashboard/alerts',
  '/dashboard/templates',
  '/dashboard/live',
  '/dashboard/usage',
  '/dashboard/calls',
];

export default function DashboardBackground() {
  const { quality } = usePerformance();
  const pathname = usePathname();
  const [isLight, setIsLight] = useState(false);

  useEffect(() => {
    const check = () => setIsLight(document.documentElement.classList.contains('light'));
    check();
    const observer = new MutationObserver(check);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  if (quality === 'off') return null;
  if (NO_BG_ROUTES.some(r => pathname === r || pathname.startsWith(r + '/'))) return null;

  const particleCount = quality === 'high' ? 1200 : 400;
  const dpr: [number, number] | number = quality === 'high' ? [1, 2] : 1;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 0,
        pointerEvents: 'none',
        opacity: quality === 'high' ? 0.35 : 0.2,
      }}
    >
      <Canvas
        camera={{ position: [0, 0, 6], fov: 60 }}
        dpr={dpr}
        gl={{ alpha: true, antialias: quality === 'high', powerPreference: 'high-performance' }}
        style={{ background: 'transparent' }}
      >
        <Scene particleCount={particleCount} isLight={isLight} />
      </Canvas>
    </div>
  );
}
