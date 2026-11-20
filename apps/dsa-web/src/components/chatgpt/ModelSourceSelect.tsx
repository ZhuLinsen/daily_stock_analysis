import { Link } from 'react-router-dom';
import { useChatGPTStore } from '../../stores/chatgptStore';

export function ModelSourceSelect({ selected, onChange }: { selected: boolean; onChange: (selected: boolean) => void }) {
  const status = useChatGPTStore((state) => state.status);
  const model = useChatGPTStore((state) => state.model);
  const name = useChatGPTStore((state) => state.models.find(({ slug }) => slug === model)?.display_name);
  if (!selected && !status?.available) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-secondary-text">
      <label className="flex items-center gap-2">
        模型来源
        <select className="max-w-52 rounded-lg border border-subtle bg-surface px-2 py-1.5" value={selected ? 'chatgpt' : 'default'} onChange={(event) => onChange(event.target.value === 'chatgpt')}>
          <option value="default">现有配置</option>
          <option value="chatgpt">ChatGPT 授权</option>
        </select>
      </label>
      {selected && (status?.connected && model
        ? <span className="break-all">{name || model} · 使用 ChatGPT 套餐</span>
        : <Link to="/settings" className="underline">在模型设置中连接并选择模型</Link>)}
    </div>
  );
}
