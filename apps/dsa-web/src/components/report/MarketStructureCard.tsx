import type React from 'react';
import { AlertTriangle, Map, TrendingUp } from 'lucide-react';
import type {
  MarketStructureContext,
  MarketStructureStatus,
  MarketStructureThemePhase,
  MarketStructureStockRole,
  RankedThemeItem,
  ReportLanguage,
} from '../../types/analysis';
import { normalizeReportLanguage } from '../../utils/reportLanguage';
import { Badge, Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';

interface MarketStructureCardProps {
  context?: MarketStructureContext | null;
  language?: ReportLanguage;
}

type BadgeVariant = NonNullable<React.ComponentProps<typeof Badge>['variant']>;

const STATUS_VARIANT: Record<MarketStructureStatus, BadgeVariant> = {
  ok: 'success',
  partial: 'warning',
  unknown: 'default',
  not_supported: 'default',
};

const TEXT = {
  zh: {
    eyebrow: '市场位置',
    title: '题材主线与个股位置',
    marketLayer: '大盘题材层',
    stockLayer: '个股位置层',
    activeThemes: '活跃题材',
    leadingConcepts: '领涨概念',
    leadingIndustries: '领涨行业',
    primaryTheme: '主关联题材',
    themePhase: '题材阶段',
    stockRole: '个股位置',
    riskTags: '风险标签',
    dataQuality: '数据质量',
    missingFields: '缺失证据',
    empty: '暂无',
    status: {
      ok: '可用',
      partial: '部分可用',
      unknown: '未知',
      not_supported: '不支持',
    },
    phase: {
      warming: '升温',
      accelerating: '加速',
      cooling: '降温',
      unknown: '未知',
    },
    role: {
      leader: '龙头',
      follower: '跟随',
      edge: '边缘关联',
      unknown: '未知',
    },
  },
  en: {
    eyebrow: 'MARKET POSITION',
    title: 'Themes and Stock Position',
    marketLayer: 'Market Theme Layer',
    stockLayer: 'Stock Position Layer',
    activeThemes: 'Active Themes',
    leadingConcepts: 'Leading Concepts',
    leadingIndustries: 'Leading Industries',
    primaryTheme: 'Primary Theme',
    themePhase: 'Theme Phase',
    stockRole: 'Stock Role',
    riskTags: 'Risk Tags',
    dataQuality: 'Data Quality',
    missingFields: 'Missing Evidence',
    empty: 'None',
    status: {
      ok: 'Available',
      partial: 'Partial',
      unknown: 'Unknown',
      not_supported: 'Not supported',
    },
    phase: {
      warming: 'Warming',
      accelerating: 'Accelerating',
      cooling: 'Cooling',
      unknown: 'Unknown',
    },
    role: {
      leader: 'Leader',
      follower: 'Follower',
      edge: 'Edge',
      unknown: 'Unknown',
    },
  },
  ko: {
    eyebrow: '시장 포지션',
    title: '테마 라인 및 종목 포지션',
    marketLayer: '시장 테마 레이어',
    stockLayer: '종목 포지션 레이어',
    activeThemes: '활성 테마',
    leadingConcepts: '선도 테마',
    leadingIndustries: '선도 산업',
    primaryTheme: '주요 관련 테마',
    themePhase: '테마 단계',
    stockRole: '종목 역할',
    riskTags: '리스크 태그',
    dataQuality: '데이터 품질',
    missingFields: '부족한 근거',
    empty: '없음',
    status: {
      ok: '사용 가능',
      partial: '일부 사용',
      unknown: '알 수 없음',
      not_supported: '미지원',
    },
    phase: {
      warming: '온도 상승',
      accelerating: '가속',
      cooling: '쿨다운',
      unknown: '알 수 없음',
    },
    role: {
      leader: '리더',
      follower: '추종',
      edge: '엣지',
      unknown: '알 수 없음',
    },
  },
} as const;

const RISK_TAG_TEXT = {
  zh: {
    theme_data_partial: '题材主线数据不完整',
    stock_theme_evidence_partial: '个股板块未匹配到市场题材榜单，个股位置按降级证据处理',
    board_membership_missing: '缺少个股所属板块证据，无法判断题材位置',
  },
  en: {
    theme_data_partial: 'Market theme data is incomplete',
    stock_theme_evidence_partial: 'Stock board did not match theme rankings',
    board_membership_missing: 'Stock board membership evidence is missing',
  },
  ko: {
    theme_data_partial: '테마 데이터가 불완전합니다',
    stock_theme_evidence_partial: '종목 보드가 테마 랭킹과 일치하지 않았습니다',
    board_membership_missing: '종목 보드 근거가 없어 테마 위치를 판단할 수 없습니다',
  },
} as const;

const formatItem = (item: RankedThemeItem): string => {
  if (typeof item.changePct === 'number') {
    return `${item.name} ${item.changePct > 0 ? '+' : ''}${item.changePct.toFixed(2)}%`;
  }
  return item.name;
};

const itemList = (items?: RankedThemeItem[], limit = 4): string[] => {
  if (!Array.isArray(items)) {
    return [];
  }
  return items.filter((item) => item?.name).slice(0, limit).map(formatItem);
};

const valueList = (items?: string[], limit = 4): string[] => {
  if (!Array.isArray(items)) {
    return [];
  }
  return items.filter(Boolean).slice(0, limit);
};

export const MarketStructureCard: React.FC<MarketStructureCardProps> = ({ context, language }) => {
  if (!context || context.schemaVersion !== 'market-structure-v1' || context.status === 'not_supported') {
    return null;
  }

  const reportLanguage = normalizeReportLanguage(language);
  const text = reportLanguage === 'en'
    ? TEXT.en
    : reportLanguage === 'ko'
      ? TEXT.ko
      : TEXT.zh;
  const marketTheme = context.marketThemeContext;
  const stockPosition = context.stockMarketPosition;
  if (!marketTheme || !stockPosition) {
    return null;
  }

  const activeThemes = itemList(marketTheme.activeThemes);
  const leadingConcepts = itemList(marketTheme.leadingConcepts);
  const leadingIndustries = itemList(marketTheme.leadingIndustries);
  const primaryTheme = stockPosition.primaryTheme?.name || text.empty;
  const themePhase = (stockPosition.themePhase || 'unknown') as MarketStructureThemePhase;
  const stockRole = (stockPosition.stockRole || 'unknown') as MarketStructureStockRole;
  const themePhaseLabel = text.phase[themePhase] || stockPosition.themePhase || text.phase.unknown;
  const stockRoleLabel = text.role[stockRole] || stockPosition.stockRole || text.role.unknown;
  const riskTags = valueList(
    stockPosition.riskTags?.map(
      (tag) =>
        (RISK_TAG_TEXT[reportLanguage] as Record<string, string>)[tag.code]
        || tag.message
        || tag.code,
    ),
  );
  const missingFields = valueList([
    ...(stockPosition.missingFields || []),
    ...(marketTheme.dataQuality?.missingFields || []),
  ]);

  const hasContent = [
    activeThemes,
    leadingConcepts,
    leadingIndustries,
    riskTags,
    missingFields,
  ].some((items) => items.length > 0) || primaryTheme !== text.empty;
  if (!hasContent) {
    return null;
  }

  return (
    <Card padding="md" className="rounded-lg">
      <section aria-label={text.title}>
        <DashboardPanelHeader
          leading={<Map className="h-4 w-4 text-cyan" aria-hidden="true" />}
          eyebrow={text.eyebrow}
          title={text.title}
          actions={
            <Badge variant={STATUS_VARIANT[context.status] || 'default'}>
              {text.status[context.status] || context.status}
            </Badge>
          }
        />

        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
              <TrendingUp className="h-4 w-4 text-success" aria-hidden="true" />
              <span>{text.marketLayer}</span>
              <Badge variant={STATUS_VARIANT[marketTheme.status] || 'default'}>
                {text.status[marketTheme.status] || marketTheme.status}
              </Badge>
            </div>
            <MetricLine label={text.activeThemes} values={activeThemes} emptyText={text.empty} />
            <MetricLine label={text.leadingConcepts} values={leadingConcepts} emptyText={text.empty} />
            <MetricLine label={text.leadingIndustries} values={leadingIndustries} emptyText={text.empty} />
          </div>

          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
              <Map className="h-4 w-4 text-cyan" aria-hidden="true" />
              <span>{text.stockLayer}</span>
              <Badge variant={STATUS_VARIANT[stockPosition.status] || 'default'}>
                {text.status[stockPosition.status] || stockPosition.status}
              </Badge>
            </div>
            <MetricLine label={text.primaryTheme} values={[primaryTheme]} emptyText={text.empty} />
            <MetricLine
              label={text.themePhase}
              values={[themePhaseLabel]}
              emptyText={text.empty}
            />
            <MetricLine
              label={text.stockRole}
              values={[stockRoleLabel]}
              emptyText={text.empty}
            />
          </div>
        </div>

        {(riskTags.length > 0 || missingFields.length > 0) && (
          <div className="mt-4 grid gap-3 border-t border-border/60 pt-4 md:grid-cols-2">
            {riskTags.length > 0 && (
              <div>
                <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-secondary-text">
                  <AlertTriangle className="h-3.5 w-3.5 text-warning" aria-hidden="true" />
                  <span>{text.riskTags}</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {riskTags.map((item) => (
                    <Badge key={item} variant="warning">{item}</Badge>
                  ))}
                </div>
              </div>
            )}
            {missingFields.length > 0 && (
              <div>
                <div className="mb-2 text-xs font-medium uppercase tracking-wide text-secondary-text">
                  {text.missingFields}
                </div>
                <div className="flex flex-wrap gap-2">
                  {missingFields.map((item) => (
                    <Badge key={item} variant="default">{item}</Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </Card>
  );
};

interface MetricLineProps {
  label: string;
  values: string[];
  emptyText: string;
}

const MetricLine: React.FC<MetricLineProps> = ({ label, values, emptyText }) => (
  <div className="grid gap-1 text-sm sm:grid-cols-[7rem_1fr]">
    <span className="text-secondary-text">{label}</span>
    <span className="min-w-0 break-words text-foreground">
      {values.length > 0 ? values.join(' / ') : emptyText}
    </span>
  </div>
);
