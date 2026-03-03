import type React from 'react';
import { useState, useEffect, useRef } from 'react';
import { getSentimentLabel } from '../../types/analysis';

interface ScoreGaugeProps {
  score: number;
  size?: 'sm' | 'md' | 'lg';
  showLabel?: boolean;
  className?: string;
}

/**
 * 情绪评分仪表盘 - 发光环形进度条
 * 参考金融终端风格设计，带过渡动画
 */
export const ScoreGauge: React.FC<ScoreGaugeProps> = ({
  score,
  size = 'md',
  showLabel = true,
  className = '',
}) => {
  // 动画状态
  const [animatedScore, setAnimatedScore] = useState(0);
  const [displayScore, setDisplayScore] = useState(0);
  const animationRef = useRef<number | null>(null);
  const prevScoreRef = useRef(0);

  // 动画效果
  useEffect(() => {
    const startScore = prevScoreRef.current;
    const endScore = score;
    const duration = 1000; // 动画时长 ms
    const startTime = performance.now();

    const animate = (currentTime: number) => {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      
      // 使用 easeOutCubic 缓动函数
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

  const label = getSentimentLabel(score);

  // 尺寸配置
  const sizeConfig = {
    sm: { width: 100, stroke: 8, fontSize: 'text-2xl', labelSize: 'text-xs', gap: 6 },
    md: { width: 140, stroke: 10, fontSize: 'text-4xl', labelSize: 'text-sm', gap: 8 },
    lg: { width: 180, stroke: 12, fontSize: 'text-5xl', labelSize: 'text-base', gap: 10 },
  };

  const { width, stroke, fontSize, labelSize, gap } = sizeConfig[size];
  const radius = (width - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  
  // 从顶部开始，显示 270 度（3/4 圆弧）
  const arcLength = circumference * 0.75;
  const progress = (animatedScore / 100) * arcLength;

  // 颜色映射 - 使用动画分数计算颜色过渡
  const getStrokeColor = (s: number) => {
    if (s >= 60) return '#00d4ff'; // 青色 - 贪婪
    if (s >= 40) return '#a855f7'; // 紫色 - 中性
    return '#ff4466'; // 红色 - 恐惧
  };

  const strokeColor = getStrokeColor(animatedScore);
  const glowColor = `${strokeColor}66`;

  return (
    <div className={`flex flex-col items-center ${className}`}>
      {/* 标题 */}
      {showLabel && (
        <span className="label-uppercase mb-3 text-secondary">
          恐惧贪婪指数
        </span>
      )}

      <div className="relative" style={{ width, height: width }}>
        <svg 
          className="gauge-ring overflow-visible" 
          width={width} 
          height={width}
          style={{ filter: `drop-shadow(0 0 12px ${glowColor})` }}
        >
          <defs>
            {/* 渐变定义 */}
            <linearGradient id={`gauge-gradient-${score}`} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor={strokeColor} stopOpacity="0.6" />
              <stop offset="100%" stopColor={strokeColor} stopOpacity="1" />
            </linearGradient>
            
            {/* 发光滤镜 */}
            <filter id={`gauge-glow-${score}`}>
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* 背景轨道 - 3/4 圆弧 */}
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

          {/* 发光层 */}
          <circle
            cx={width / 2}
            cy={width / 2}
            r={radius}
            fill="none"
            stroke={strokeColor}
            strokeWidth={stroke + gap}
            strokeLinecap="round"
            strokeDasharray={`${progress} ${circumference}`}
            transform={`rotate(135 ${width / 2} ${width / 2})`}
            opacity="0.3"
            filter={`url(#gauge-glow-${score})`}
          />

          {/* 进度圆弧 */}
          <circle
            cx={width / 2}
            cy={width / 2}
            r={radius}
            fill="none"
            stroke={`url(#gauge-gradient-${score})`}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${progress} ${circumference}`}
            transform={`rotate(135 ${width / 2} ${width / 2})`}
          />
        </svg>

        {/* 中心数值 */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className={`font-bold ${fontSize} text-white`}
            style={{ 
              textShadow: `0 0 30px ${glowColor}`,
            }}
          >
            {displayScore}
          </span>
          {showLabel && (
            <span
              className={`${labelSize} font-semibold mt-1`}
              style={{ color: strokeColor }}
            >
              {label.toUpperCase()}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
