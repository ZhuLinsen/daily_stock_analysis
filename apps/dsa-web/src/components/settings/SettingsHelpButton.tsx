import { CircleHelp, ExternalLink, X } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import type React from 'react';
import { createPortal } from 'react-dom';
import type { SystemConfigFieldSchema } from '../../types/systemConfig';
import { getSettingsHelpContent } from '../../locales/settingsHelp';
import { cn } from '../../utils/cn';
import { Tooltip } from '../common';

interface SettingsHelpButtonProps {
  fieldKey: string;
  title: string;
  schema?: SystemConfigFieldSchema;
  description?: string;
}

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

function hasItems<T>(items: T[] | undefined): items is T[] {
  return Boolean(items?.length);
}

function HelpSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  if (!children) {
    return null;
  }

  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-text">{title}</h3>
      {children}
    </section>
  );
}

function HelpList({ items }: { items?: string[] }) {
  if (!hasItems(items)) {
    return null;
  }

  return (
    <ul className="space-y-1.5 text-sm leading-6 text-secondary-text">
      {items.map((item) => (
        <li className="flex gap-2" key={item}>
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan/70" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function CodeExamples({ examples }: { examples?: string[] }) {
  if (!hasItems(examples)) {
    return null;
  }

  return (
    <div className="space-y-2">
      {examples.map((example) => (
        <code
          className="block whitespace-pre-wrap break-words rounded-lg border border-border/70 bg-background/70 px-3 py-2 font-mono text-xs leading-5 text-foreground"
          key={example}
        >
          {example}
        </code>
      ))}
    </div>
  );
}

export const SettingsHelpButton: React.FC<SettingsHelpButtonProps> = ({
  fieldKey,
  title,
  schema,
  description,
}) => {
  const help = getSettingsHelpContent(schema?.helpKey, description);
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  const examples = schema?.examples ?? [];
  const docs = schema?.docs?.length ? schema.docs : help?.docs ?? [];

  useEffect(() => {
    if (!open) {
      return;
    }

    const focusDialogStart = () => {
      closeButtonRef.current?.focus();
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        return;
      }

      if (event.key !== 'Tab') {
        return;
      }

      const dialog = dialogRef.current;
      if (!dialog) {
        return;
      }

      const focusableElements = getFocusableElements(dialog);
      if (!focusableElements.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement;

      if (event.shiftKey) {
        if (!activeElement || !dialog.contains(activeElement) || activeElement === firstElement) {
          event.preventDefault();
          lastElement.focus();
        }
        return;
      }

      if (!activeElement || !dialog.contains(activeElement) || activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    const previousOverflow = document.body.style.overflow;
    const triggerButton = buttonRef.current;
    document.body.style.overflow = 'hidden';
    focusDialogStart();

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = previousOverflow;
      triggerButton?.focus();
    };
  }, [open]);

  if (!help) {
    return null;
  }

  return (
    <>
      <Tooltip content="查看配置说明">
        <span className="inline-flex">
          <button
            ref={buttonRef}
            type="button"
            className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-transparent text-muted-text transition-colors hover:border-[var(--settings-border)] hover:bg-[var(--settings-surface-hover)] hover:text-foreground focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan/15"
            aria-label={`查看 ${title} 配置说明`}
            aria-expanded={open}
            aria-controls={open ? titleId : undefined}
            onClick={() => setOpen(true)}
          >
            <CircleHelp aria-hidden="true" className="h-4 w-4" />
          </button>
        </span>
      </Tooltip>

      {open && typeof document !== 'undefined'
        ? createPortal(
            <div className="fixed inset-0 z-[140] flex items-end bg-background/25 backdrop-blur-sm sm:items-center sm:justify-center">
              <button
                type="button"
                className="absolute inset-0 cursor-default"
                aria-label="关闭配置说明"
                tabIndex={-1}
                onClick={() => setOpen(false)}
              />
              <div
                ref={dialogRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                tabIndex={-1}
                className={cn(
                  'relative flex max-h-[88vh] w-full flex-col overflow-hidden rounded-t-2xl border border-border/80 bg-card shadow-soft-card-strong',
                  'sm:max-w-2xl sm:rounded-2xl',
                )}
              >
                <div className="h-1 w-full bg-gradient-to-r from-cyan/80 via-primary/70 to-purple/70" />
                <div className="flex items-start justify-between gap-4 border-b border-border/60 px-5 py-4">
                  <div className="min-w-0">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-text">
                      {fieldKey}
                    </p>
                    <h2 id={titleId} className="mt-1 text-lg font-semibold text-foreground">
                      {help.title || title}
                    </h2>
                    {help.summary ? (
                      <p className="mt-2 text-sm leading-6 text-secondary-text">{help.summary}</p>
                    ) : null}
                  </div>
                  <button
                    ref={closeButtonRef}
                    type="button"
                    onClick={() => setOpen(false)}
                    className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-border/70 bg-card/80 text-secondary-text transition-colors hover:bg-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan/15"
                    aria-label="关闭配置说明"
                  >
                    <X aria-hidden="true" className="h-4 w-4" />
                  </button>
                </div>

                <div className="space-y-5 overflow-y-auto px-5 py-5">
                  <HelpSection title="用途">
                    {help.usage ? <p className="text-sm leading-6 text-secondary-text">{help.usage}</p> : null}
                  </HelpSection>

                  <HelpSection title="取值说明">
                    <HelpList items={help.valueNotes} />
                  </HelpSection>

                  <HelpSection title="配置样例">
                    <CodeExamples examples={examples} />
                  </HelpSection>

                  <HelpSection title="影响范围">
                    <HelpList items={help.impact} />
                  </HelpSection>

                  <HelpSection title="注意事项">
                    <HelpList items={help.notes} />
                  </HelpSection>

                  {hasItems(docs) ? (
                    <HelpSection title="相关文档">
                      <div className="flex flex-wrap gap-2">
                        {docs.map((doc) => (
                          <a
                            className="inline-flex items-center gap-1.5 rounded-lg border border-border/70 bg-background/60 px-3 py-2 text-xs text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
                            href={doc.href}
                            key={`${doc.label}-${doc.href}`}
                            rel="noreferrer"
                            target="_blank"
                          >
                            <span>{doc.label}</span>
                            <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
                          </a>
                        ))}
                      </div>
                    </HelpSection>
                  ) : null}
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
};
