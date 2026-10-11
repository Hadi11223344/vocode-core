"use client";

import { Download, Pause, Play, Volume2 } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";

interface TranscriptLine {
  role: "agent" | "customer";
  message: string;
  timestamp: string;
}

interface CallRecordingPlayerProps {
  recordingUrl: string;
  transcript: TranscriptLine[];
}

export function CallRecordingPlayer({
  recordingUrl,
  transcript,
}: CallRecordingPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [activeLine, setActiveLine] = useState<number | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [volume, setVolume] = useState(1);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Compute approximate offsets from transcript timestamps
  const linesWithOffsets = React.useMemo(() => {
    if (!transcript.length) return [];

    const startTime = new Date(transcript[0].timestamp).getTime();
    return transcript.map((line, index) => {
      const lineTime = new Date(line.timestamp).getTime();
      const offsetMs = lineTime - startTime;
      return {
        ...line,
        offsetSeconds: Math.max(0, offsetMs / 1000),
        index,
      };
    });
  }, [transcript]);

  // Update active line based on playback position
  useEffect(() => {
    let currentLine: (typeof linesWithOffsets)[0] | undefined;
    for (let i = linesWithOffsets.length - 1; i >= 0; i--) {
      if (currentTime >= linesWithOffsets[i].offsetSeconds) {
        currentLine = linesWithOffsets[i];
        break;
      }
    }
    const newIndex = currentLine?.index ?? null;
    if (newIndex !== activeLine) {
      setActiveLine(newIndex);
      // Auto-scroll active line into view
      if (newIndex !== null && scrollRef.current) {
        const lineEl = scrollRef.current.querySelector(
          `[data-line-index="${newIndex}"]`
        );
        lineEl?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }
  }, [currentTime, linesWithOffsets, activeLine]);

  const handleTimeUpdate = () => {
    if (audioRef.current) {
      setCurrentTime(audioRef.current.currentTime);
    }
  };

  const handleLoadedMetadata = () => {
    if (audioRef.current) {
      setDuration(audioRef.current.duration);
    }
  };

  const togglePlay = () => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause();
      } else {
        audioRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  };

  const handleEnded = () => {
    setIsPlaying(false);
  };

  const seekToLine = (offsetSeconds: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = offsetSeconds;
      audioRef.current.play();
      setIsPlaying(true);
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = parseFloat(e.target.value);
    if (audioRef.current) {
      audioRef.current.currentTime = time;
      setCurrentTime(time);
    }
  };

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const vol = parseFloat(e.target.value);
    setVolume(vol);
    if (audioRef.current) {
      audioRef.current.volume = vol;
    }
  };

  const formatTime = (seconds: number): string => {
    if (!isFinite(seconds)) return "0:00";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
      {/* Audio Player Controls */}
      <div className="p-4 border-b border-gray-100">
        <audio
          ref={audioRef}
          src={recordingUrl}
          onTimeUpdate={handleTimeUpdate}
          onLoadedMetadata={handleLoadedMetadata}
          onEnded={handleEnded}
          className="hidden"
        />

        <div className="flex items-center gap-4">
          <button
            onClick={togglePlay}
            className="w-10 h-10 flex items-center justify-center rounded-full bg-blue-600 text-white hover:bg-blue-700 transition-colors"
            aria-label={isPlaying ? "Pause" : "Play"}
          >
            {isPlaying ? (
              <Pause className="w-4 h-4" />
            ) : (
              <Play className="w-4 h-4 ml-0.5" />
            )}
          </button>

          <div className="flex-1 flex items-center gap-3">
            <span className="text-sm font-mono text-gray-500 w-12 text-right">
              {formatTime(currentTime)}
            </span>
            <input
              type="range"
              min={0}
              max={duration || 0}
              step={0.1}
              value={currentTime}
              onChange={handleSeek}
              className="flex-1 h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-blue-600"
            />
            <span className="text-sm font-mono text-gray-500 w-12">
              {formatTime(duration)}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <Volume2 className="w-4 h-4 text-gray-400" />
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={volume}
              onChange={handleVolumeChange}
              className="w-20 h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-blue-600"
            />
          </div>

          <a
            href={recordingUrl}
            download
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            Download
          </a>
        </div>
      </div>

      {/* Transcript with click-to-seek */}
      <div
        ref={scrollRef}
        className="max-h-96 overflow-y-auto p-2 space-y-1"
      >
        {linesWithOffsets.length === 0 && (
          <p className="text-sm text-gray-400 text-center py-8">
            No transcript available for this call.
          </p>
        )}
        {linesWithOffsets.map((line) => (
          <div
            key={line.index}
            data-line-index={line.index}
            onClick={() => seekToLine(line.offsetSeconds)}
            className={`
              p-2 rounded-md cursor-pointer transition-colors
              ${line.role === "agent" ? "bg-blue-50/70" : "bg-gray-50/70"}
              ${activeLine === line.index ? "ring-2 ring-blue-400 bg-blue-100/70" : "hover:bg-blue-50"}
            `}
          >
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-xs font-mono text-gray-400 select-none">
                {formatTime(line.offsetSeconds)}
              </span>
              <span
                className={`text-xs font-semibold ${
                  line.role === "agent"
                    ? "text-blue-600"
                    : "text-gray-600"
                }`}
              >
                {line.role === "agent" ? "AI" : "Customer"}
              </span>
            </div>
            <p className="text-sm text-gray-800 leading-relaxed pl-[52px]">
              {line.message}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
