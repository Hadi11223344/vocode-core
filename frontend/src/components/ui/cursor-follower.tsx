'use client';

import { useEffect, useRef, useCallback } from 'react';

export function CursorFollower() {
  const dotRef = useRef<HTMLDivElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);
  const pos = useRef({ x: -200, y: -200 });
  const target = useRef({ x: -200, y: -200 });
  const scale = useRef(1);
  const opacity = useRef(0);  // start hidden until first mouse move
  const raf = useRef<number>(0);
  const visible = useRef(false);

  const animate = useCallback(() => {
    // Smooth lerp for ring (outer glow)
    pos.current.x += (target.current.x - pos.current.x) * 0.15;
    pos.current.y += (target.current.y - pos.current.y) * 0.15;

    if (dotRef.current) {
      dotRef.current.style.transform = `translate(${target.current.x}px, ${target.current.y}px) translate(-50%, -50%) scale(${scale.current})`;
      dotRef.current.style.opacity = String(opacity.current);
    }
    if (ringRef.current) {
      ringRef.current.style.transform = `translate(${pos.current.x}px, ${pos.current.y}px) translate(-50%, -50%) scale(${scale.current})`;
      ringRef.current.style.opacity = String(opacity.current * 0.5);
    }

    raf.current = requestAnimationFrame(animate);
  }, []);

  useEffect(() => {
    // Only show on non-touch devices
    const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
    if (isTouchDevice) return;

    function onMouseMove(e: MouseEvent) {
      target.current = { x: e.clientX, y: e.clientY };
      if (!visible.current) {
        visible.current = true;
        opacity.current = 1;
      }
    }

    function onMouseDown() {
      scale.current = 0.8;
    }

    function onMouseUp() {
      scale.current = 1;
    }

    function onMouseLeaveWindow() {
      opacity.current = 0;
      visible.current = false;
    }

    function onMouseEnterWindow() {
      opacity.current = 1;
      visible.current = true;
    }

    const interactiveSelector = 'a, button, [role="button"], input, textarea, select, .card-interactive, .btn-primary, .btn-secondary, .btn-ghost';

    function onDelegatedMouseEnter(e: MouseEvent) {
      const target = e.target as HTMLElement;
      if (target.closest(interactiveSelector)) {
        scale.current = 1.8;
      }
    }

    function onDelegatedMouseLeave(e: MouseEvent) {
      const target = e.target as HTMLElement;
      if (target.closest(interactiveSelector)) {
        scale.current = 1;
      }
    }

    window.addEventListener('mousemove', onMouseMove, { passive: true });
    window.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mouseup', onMouseUp);
    document.documentElement.addEventListener('mouseleave', onMouseLeaveWindow);
    document.documentElement.addEventListener('mouseenter', onMouseEnterWindow);
    document.addEventListener('mouseover', onDelegatedMouseEnter, { passive: true });
    document.addEventListener('mouseout', onDelegatedMouseLeave, { passive: true });
    raf.current = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(raf.current);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mouseup', onMouseUp);
      document.documentElement.removeEventListener('mouseleave', onMouseLeaveWindow);
      document.documentElement.removeEventListener('mouseenter', onMouseEnterWindow);
      document.removeEventListener('mouseover', onDelegatedMouseEnter);
      document.removeEventListener('mouseout', onDelegatedMouseLeave);
    };
  }, [animate]);

  return (
    <>
      {/* Inner dot */}
      <div
        ref={dotRef}
        className="cursor-dot"
        aria-hidden="true"
      />
      {/* Outer ring / glow */}
      <div
        ref={ringRef}
        className="cursor-ring"
        aria-hidden="true"
      />
    </>
  );
}
