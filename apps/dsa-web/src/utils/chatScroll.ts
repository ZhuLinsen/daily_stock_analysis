interface ScrollMetrics {
  scrollTop: number;
  clientHeight: number;
  scrollHeight: number;
}

const DEFAULT_THRESHOLD = 96;

export function isNearBottom(
  metrics: ScrollMetrics,
  threshold = DEFAULT_THRESHOLD,
): boolean {
  const distanceFromBottom =
    metrics.scrollHeight - (metrics.scrollTop + metrics.clientHeight);

  return distanceFromBottom <= threshold;
}
