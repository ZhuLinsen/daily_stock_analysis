import type React from 'react';
import { useState, useEffect, useRef } from 'react';
import { getSentimentLabel, type ReportLanguage } from '../../types/analysis';
import { cn } from '../../utils/cn';
import { normalizeReportLanguage, getReportText } from '../../utils/reportLanguage';

interface ScoreGaugeProps {
  score: number;
  size?: 'sm' | 'md' | 'lg';
  showLabel?: boolean;
  className?: string;
  language?: ReportLanguage;
}

/**
 * Sentiment score gauge with an animated glowing ring.
 * Dynamically calculates colors based on sentiment score.
 */
export const ScoreGauge: React.FC<ScoreGaugeProps> = ({
  score,
  size = 'md',
  showLabel = true,
  className = '',
  language = 'zh',
}) => {
  // Animated score state.
  const [animatedScore, setAnimatedScore] = useState(0);
  const [displayScore, setDisplayScore] = useState(0);
  const animationRef = useRef<number | null>(null);
  const prevScoreRef = useRef(0);

  // Animate transitions between score updates.
  useEffect(() => {
    const startScore = prevScoreRef.current;
    const endScore = score;
    const duration = 1000; // Animation duration in ms.
    const startTime = performance.now();

    const animate = (currentTime: number) => {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);

      // Use an ease-out cubic curve for a smoother finish.
      const easeOut = 1 - Math.pow(1 - progress, 3);

      const currentScore = startScore + (endScore - startScore) * easeOut;
      setAnimatedScore(currentScore);
      setDisplayScore(Math.round(currentScore));

      if (progress < 1) {
        animationRef.current = requestAnimationFrame(animate);
      } else {
        prevScoreRef.current = endScore;
      }
    };

    animationRef.current = requestAnimationFrame(animate);

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [score]);

  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const label = getSentimentLabel(score, reportLanguage);

  // Size configuration for each gauge variant.
  const sizeConfig = {
    sm: { width: 100, stroke: 8, fontSize: 'text-2xl', labelSize: 'text-xs', gap: 6 },
    md: { width: 140, stroke: 10, fontSize: 'text-4xl', labelSize: 'text-sm', gap: 8 },
    lg: { width: 180, stroke: 12, fontSize: 'text-5xl', labelSize: 'text-base', gap: 10 },
  };

  const { width, stroke, fontSize, labelSize, gap } = sizeConfig[size];
  const radius = (width - stroke) / 2;
  const circumference = 2 * Math.PI * radius;

  // Start from the top and render a 270-degree arc.
  const arcLength = circumference * 0.75;
  const progress = (animatedScore / 100) * arcLength;

  // Sentiment colors - dynamically computed based on score thresholds
  // These match the original branch's color values for consistency
  const sentimentConfig = {
    greed: {
      color: '#00d4ff',       // Cyan
      colorHsl: 'hsl(193, 100%, 43%)',
      glow: 'rgba(0, 212, 255, 0.4)',
      glowFilter: 'rgba(0, 212, 255, 0.66)',
    },
    neutral: {
      color: '#a855f7',       // Purple
      colorHsl: 'hsl(247, 84%, 66%)',
      glow: 'rgba(168, 85, 247, 0.4)',
      glowFilter: 'rgba(168, 85, 247, 0.66)',
    },
    fear: {
      color: '#ff4466',       // Red
      colorHsl: 'hsl(349, 82%, 56%)',
      glow: 'rgba(255, 68, 102, 0.4)',
      glowFilter: 'rgba(255, 68, 102, 0.66)',
    },
  };

  // Map score to sentiment key
  const getSentimentKey = (s: number): 'greed' | 'neutral' | 'fear' => {
    if (s >= 60) return 'greed';
    if (s >= 40) return 'neutral';
    return 'fear';
  };

  const sentimentKey = getSentimentKey(animatedScore);
  const colors = sentimentConfig[sentimentKey];
  const uniqueId = `${sentimentKey}-${score}-${animatedScore.toFixed(0)}`;

  return (
    <div className={cn('flex flex-col items-center', className)}>
      {showLabel && (
        <span className="label-uppercase mb-3 text-secondary-text">
          {text.fearGreedIndex}
        </span>
      )}

      <div className="relative" style={{ width, height: width }}>
        <svg
          className="gauge-ring overflow-visible"
          width={width}
          height={width}
          style={{
            filter: `drop-shadow(0 0 12px ${colors.glowFilter})`,
          }}
        >
          <defs>
            {/* Gradient definition */}
            <linearGradient id={`gauge-gradient-${uniqueId}`} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor={colors.color} stopOpacity="0.6" />
              <stop offset="100%" stopColor={colors.color} stopOpacity="1" />
            </linearGradient>

            {/* Glow filter */}
            <filter id={`gauge-glow-${uniqueId}`}>
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* Background track */}
          <circle
            cx={width / 2}
            cy={width / 2}
            r={radius}
            fill="none"
            stroke="rgba(255, 255, 255, 0.05)"
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${arcLength} ${circumference}`}
            transform={`rotate(135 ${width / 2} ${width / 2})`}
          />

          {/* Glow layer */}
          <circle
            cx={width / 2}
            cy={width / 2}
            r={radius}
            fill="none"
            stroke={colors.color}
            strokeWidth={stroke + gap}
            strokeLinecap="round"
            strokeDasharray={`${progress} ${circumference}`}
            transform={`rotate(135 ${width / 2} ${width / 2})`}
            opacity="0.3"
            filter={`url(#gauge-glow-${uniqueId})`}
          />

          {/* Progress arc */}
          <circle
            cx={width / 2}
            cy={width / 2}
            r={radius}
            fill="none"
            stroke={`url(#gauge-gradient-${uniqueId})`}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${progress} ${circumference}`}
            transform={`rotate(135 ${width / 2} ${width / 2})`}
          />
        </svg>

        {/* Center value */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className={cn('font-bold text-white', fontSize)}
            style={{ textShadow: `0 0 30px ${colors.glowFilter}` }}
          >
            {displayScore}
          </span>
          {showLabel && (
            <span
              className={`${labelSize} font-semibold mt-1`}
              style={{ color: colors.color }}
            >
              {label.toUpperCase()}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
