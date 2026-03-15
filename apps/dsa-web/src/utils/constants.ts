// 生产环境使用相对路径（同源），开发环境使用环境变量或默认本地地址
export const API_BASE_URL = import.meta.env.VITE_API_URL || (import.meta.env.PROD ? '' : 'http://127.0.0.1:8000');
