import type React from 'react';
import { useState, useEffect, useRef } from 'react';
import { useTheme } from 'next-themes';
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

type SentimentKey = 'greed' | 'neutral' | 'fear';

type GaugeVisualStyle = {
  svgFilter?: string;
  glowBlur: number;
  glowOpacity: number;
  glowStrokeExtra: number;
  valueTextShadow?: string;
};

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
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';

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

  // Sentiment colors - dynamically computed based on score thresholds.
  // Light theme uses a restrained glow; dark theme keeps the stronger terminal-style glow.
  const sentimentConfig = {
    greed: {
      color: '#00d4ff',       // Cyan
      glowFilter: 'rgba(0, 212, 255, 0.66)',
      lightColor: '#22d3ee',  // Lighter cyan
      lightEndColor: '#0891b2', // Darker cyan
    },
    neutral: {
      color: '#a855f7',       // Purple
      glowFilter: 'rgba(168, 85, 247, 0.66)',
      lightColor: '#c084fc',  // Lighter purple
      lightEndColor: '#9333ea', // Darker purple
    },
    fear: {
      color: '#ff4466',       // Red
      glowFilter: 'rgba(255, 68, 102, 0.66)',
      lightColor: '#fb7185',  // Lighter rose
      lightEndColor: '#e11d48', // Darker rose
    },
  };

  // Map score to sentiment key
  const getSentimentKey = (s: number): SentimentKey => {
    if (s >= 60) return 'greed';
    if (s >= 40) return 'neutral';
    return 'fear';
  };

  const sentimentKey = getSentimentKey(animatedScore);
  const colors = sentimentConfig[sentimentKey];
  const uniqueId = `${sentimentKey}-${score}-${animatedScore.toFixed(0)}`;
  const gaugeTheme: GaugeVisualStyle = isDark
    ? {
        svgFilter: `drop-shadow(0 0 12px ${colors.glowFilter})`,
        glowBlur: 4,
        glowOpacity: 0.3,
        glowStrokeExtra: gap,
        valueTextShadow: `0 0 30px ${colors.glowFilter}`,
      }
    : {
        svgFilter: `drop-shadow(0 0 8px ${colors.glowFilter.replace('0.66', '0.28')})`,
        glowBlur: 3.4,
        glowOpacity: 0.26,
        glowStrokeExtra: Math.max(3, gap * 0.55),
        valueTextShadow: `0 0 16px ${colors.glowFilter.replace('0.66', '0.22')}`,
      };

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
          style={gaugeTheme.svgFilter ? { filter: gaugeTheme.svgFilter } : {}}
        >
          <defs>
            {/* Gradient definition - dark: glow gradient; light: clean gradient */}
            <linearGradient id={`gauge-gradient-${uniqueId}`} x1="0%" y1="0%" x2="100%" y2="100%">
              {isDark ? (
                <>
                  <stop offset="0%" stopColor={colors.color} stopOpacity="0.6" />
                  <stop offset="100%" stopColor={colors.color} stopOpacity="1" />
                </>
              ) : (
                <>
                  <stop offset="0%" stopColor={colors.lightColor} stopOpacity="0.9" />
                  <stop offset="100%" stopColor={colors.lightEndColor} stopOpacity="1" />
                </>
              )}
            </linearGradient>

            <filter id={`gauge-glow-${uniqueId}`}>
              <feGaussianBlur stdDeviation={gaugeTheme.glowBlur} result="blur" />
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

          <circle
            cx={width / 2}
            cy={width / 2}
            r={radius}
            fill="none"
            stroke={isDark ? colors.color : colors.lightColor}
            strokeWidth={stroke + gaugeTheme.glowStrokeExtra}
            strokeLinecap="round"
            strokeDasharray={`${progress} ${circumference}`}
            transform={`rotate(135 ${width / 2} ${width / 2})`}
            opacity={gaugeTheme.glowOpacity}
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
            className={cn('font-bold', fontSize, isDark ? 'text-white' : 'text-foreground')}
            style={gaugeTheme.valueTextShadow ? { textShadow: gaugeTheme.valueTextShadow } : {}}
          >
            {displayScore}
          </span>
          {showLabel && (
            <span
              className={`${labelSize} font-semibold mt-1`}
              style={{ color: isDark ? colors.color : colors.lightEndColor }}
            >
              {label.toUpperCase()}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
