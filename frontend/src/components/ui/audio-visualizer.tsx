'use client';

import { useRef, useEffect } from 'react';

interface AudioVisualizerProps {
  isListening: boolean;
  barCount?: number;
}

export function AudioVisualizer({ isListening, barCount = 12 }: AudioVisualizerProps) {
  const bars = Array.from({ length: barCount }, (_, i) => i);

  return (
    <div className="flex items-center gap-[3px] h-8">
      {bars.map((i) => (
        <div
          key={i}
          className="w-[3px] rounded-full bg-[var(--accent)] transition-all duration-75"
          style={{
            height: isListening ? undefined : '4px',
            animation: isListening
              ? `audio-bar-${i % 3} ${0.4 + (i % 3) * 0.15}s ease-in-out infinite alternate`
              : 'none',
            opacity: isListening ? 1 : 0.3,
          }}
        />
      ))}
      <style jsx>{`
        @keyframes audio-bar-0 {
          0% { height: 4px; }
          100% { height: 28px; }
        }
        @keyframes audio-bar-1 {
          0% { height: 4px; }
          100% { height: 20px; }
        }
        @keyframes audio-bar-2 {
          0% { height: 4px; }
          100% { height: 32px; }
        }
      `}</style>
    </div>
  );
}

/**
 * Canvas-based real-time microphone waveform visualizer.
 * Requires a MediaStream from getUserMedia.
 */
export function MicWaveform({ stream }: { stream: MediaStream | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);
  const analyserRef = useRef<AnalyserNode | null>(null);

  useEffect(() => {
    if (!stream || !canvasRef.current) return;

    const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    analyserRef.current = analyser;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    const draw = () => {
      animRef.current = requestAnimationFrame(draw);
      analyser.getByteFrequencyData(dataArray);

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const barWidth = (canvas.width / bufferLength) * 2.5;
      let barX = 0;

      for (let i = 0; i < bufferLength; i++) {
        const barHeight = (dataArray[i] / 255) * canvas.height;
        ctx.fillStyle = `rgba(var(--accent-rgb, 99, 102, 241), ${0.3 + (dataArray[i] / 255) * 0.7})`;
        ctx.fillRect(barX, canvas.height - barHeight, barWidth, barHeight);
        barX += barWidth + 1;
      }
    };

    draw();

    return () => {
      cancelAnimationFrame(animRef.current);
      audioCtx.close();
    };
  }, [stream]);

  return (
    <canvas
      ref={canvasRef}
      width={200}
      height={40}
      className="rounded-lg bg-[var(--bg-tertiary)]"
    />
  );
}
