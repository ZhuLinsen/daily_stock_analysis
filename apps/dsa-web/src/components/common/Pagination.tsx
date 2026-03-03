import type React from 'react';

interface PageButtonProps {
  page: number | string;
  isActive?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children?: React.ReactNode;
}

const PageButton: React.FC<PageButtonProps> = ({ page, isActive, disabled, onClick, children }) => {
  const isEllipsis = page === '...';

  if (isEllipsis) {
    return <span className="px-3 py-2 text-muted">...</span>;
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`
        min-w-[40px] h-10 px-3 rounded-lg font-medium
        transition-all duration-200
        hover:bg-hover hover:text-white border border-white/5
        ${isActive ? 'bg-cyan text-muted' : 'bg-elevated text-secondary'}
        ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
      `}
    >
      {children || page}
    </button>
  );
};

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  className?: string;
}

/**
 * 分页组件 - 终端风格
 */
export const Pagination: React.FC<PaginationProps> = ({
  currentPage,
  totalPages,
  onPageChange,
  className = '',
}) => {
  if (totalPages <= 1) return null;

  // 生成页码数组
  const getPageNumbers = (): (number | string)[] => {
    const pages: (number | string)[] = [];
    const delta = 2;

    for (let i = 1; i <= totalPages; i++) {
      if (
        i === 1 ||
        i === totalPages ||
        (i >= currentPage - delta && i <= currentPage + delta)
      ) {
        pages.push(i);
      } else if (pages[pages.length - 1] !== '...') {
        pages.push('...');
      }
    }

    return pages;
  };

  return (
    <div className={`flex items-center justify-center gap-2 ${className}`}>
      {/* 上一页 */}
      <PageButton
        page="prev"
        disabled={currentPage === 1}
        onClick={() => onPageChange(currentPage - 1)}
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
      </PageButton>

      {/* 页码 */}
      {getPageNumbers().map((page, index) => (
        <PageButton
          key={`${page}-${index}`}
          page={page}
          isActive={page === currentPage}
          onClick={() => typeof page === 'number' && onPageChange(page)}
        />
      ))}

      {/* 下一页 */}
      <PageButton
        page="next"
        disabled={currentPage === totalPages}
        onClick={() => onPageChange(currentPage + 1)}
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </PageButton>
    </div>
  );
};
