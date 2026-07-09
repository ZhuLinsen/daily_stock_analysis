import type React from 'react';
import {
  CONFIDENCE_LABELS,
  STANCE_LABELS,
  adaptFourMastersCommentary,
} from './fourMastersCommentaryAdapter';
import type { FourMastersCardVM, StanceValue } from './fourMastersCommentaryAdapter';

// Phase 25.7: structured UI for the four-masters commentary supplement.
// Commentary-only surface — no action CTAs, no advice fields, escaped text only
// (plain JSX text nodes; no dangerouslySetInnerHTML anywhere in this tree).

interface FourMastersCommentarySectionProps {
  rawCommentary: unknown;
}

const STANCE_BADGE_CLASSES: Record<StanceValue, string> = {
  support: 'text-success border-success/40 bg-success/10',
  challenge: 'text-danger border-danger/40 bg-danger/10',
  mixed: 'text-warning border-warning/40 bg-warning/10',
};

function StanceBadge({ stance }: { stance: StanceValue }) {
  return (
    <span
      data-testid="four-masters-stance"
      className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-bold tracking-wide ${STANCE_BADGE_CLASSES[stance]}`}
    >
      {STANCE_LABELS[stance]}
    </span>
  );
}

function MasterCard({ card }: { card: FourMastersCardVM }) {
  return (
    <article
      data-testid={`four-masters-card-${card.key}`}
      className="flex flex-col rounded-lg border bg-background/60 p-3"
    >
      <header className="mb-2 flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-current/30 font-serif text-sm font-bold text-secondary-foreground"
          >
            {card.monogram}
          </span>
          <div>
            <h4 className="text-xs font-bold leading-tight text-foreground">{card.title}</h4>
            <p className="text-[10px] leading-tight text-muted-foreground">{card.subtitle}</p>
          </div>
        </div>
        <StanceBadge stance={card.stance} />
      </header>

      <p className="mb-2 text-xs leading-relaxed text-secondary-foreground">{card.summary}</p>

      {card.details.length > 0 && (
        <dl className="space-y-1.5 border-t border-border/50 pt-2">
          {card.details.map((detail) => (
            <div key={detail.label}>
              <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">
                {detail.label}
              </dt>
              <dd className="text-[11px] leading-snug text-secondary-foreground">{detail.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {card.redLines.length > 0 && (
        <div className="mt-2 border-t border-border/50 pt-2">
          <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-danger">紅線</p>
          <ul className="space-y-0.5">
            {card.redLines.map((line) => (
              <li key={line} className="flex gap-1.5 text-[11px] leading-snug text-secondary-foreground">
                <span aria-hidden className="mt-[3px] h-1.5 w-1.5 shrink-0 rounded-sm bg-danger/70" />
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

export const FourMastersCommentarySection: React.FC<FourMastersCommentarySectionProps> = ({
  rawCommentary,
}) => {
  const vm = adaptFourMastersCommentary(rawCommentary);
  if (!vm) return null;

  const { synthesis } = vm;
  const hasSynthesisText = Boolean(synthesis.mainDisagreement || synthesis.mostUsefulSupplement);

  return (
    <section
      data-testid="four-masters-commentary"
      className="report-light-surface mt-6 rounded-xl border bg-background print:mt-4 print:break-inside-avoid"
    >
      <header className="border-b px-4 pb-3 pt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-bold text-foreground">四大師視角補充</h3>
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            Framework Commentary
          </span>
        </div>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          投資框架模擬點評，不覆蓋原始操作建議
        </p>
      </header>

      <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2">
        {vm.cards.map((card) => (
          <MasterCard key={card.key} card={card} />
        ))}
      </div>

      <div className="px-4 pb-4">
        <div
          data-testid="four-masters-synthesis"
          className="rounded-lg border border-border bg-secondary/40 p-3"
        >
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-xs font-bold text-foreground">綜合觀察</h4>
            <span className="rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
              {CONFIDENCE_LABELS[synthesis.confidenceAdjustment]}
            </span>
          </div>
          {hasSynthesisText ? (
            <div className="space-y-1.5">
              {synthesis.mainDisagreement && (
                <p className="text-[11px] leading-snug text-secondary-foreground">
                  <span className="font-bold">主要分歧：</span>
                  {synthesis.mainDisagreement}
                </p>
              )}
              {synthesis.mostUsefulSupplement && (
                <p className="text-[11px] leading-snug text-secondary-foreground">
                  <span className="font-bold">最有用的補充：</span>
                  {synthesis.mostUsefulSupplement}
                </p>
              )}
            </div>
          ) : (
            <p className="text-[11px] text-muted-foreground">四個視角未形成額外綜合觀察。</p>
          )}
        </div>

        <p className="mt-3 text-[10px] leading-snug text-muted-foreground">
          本段為投資框架模擬點評，不代表任何人物本人觀點，且不覆蓋原始操作建議。
        </p>
      </div>
    </section>
  );
};
