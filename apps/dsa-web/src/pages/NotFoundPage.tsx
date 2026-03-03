import type React from 'react';
import { useNavigate } from 'react-router-dom';

const NotFoundPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex flex-col items-center justify-center text-center px-4">
      {/* 404 */}
      <div className="relative mb-8">
        <span 
          className="text-8xl font-bold text-transparent bg-clip-text"
          style={{
            backgroundImage: 'linear-gradient(135deg, #00d4ff 0%, #a855f7 100%)',
          }}
        >
          404
        </span>
      </div>

      <h1 className="text-2xl font-bold text-white mb-2">页面未找到</h1>
      <p className="text-muted mb-8">抱歉，您访问的页面不存在或已被移动</p>

      <button 
        type="button"
        className="btn-primary flex items-center gap-2"
        onClick={() => navigate('/')}
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
        </svg>
        返回首页
      </button>
    </div>
  );
};

export default NotFoundPage;
