import type { SearchResult } from '../types';

interface Props {
  result: SearchResult;
  rank: number;
  checked: boolean;
  onToggle: () => void;
}

export default function ResultCard({ result, rank, checked, onToggle }: Props) {
  const scorePct = Math.max(0, Math.min(Math.round(result.score * 100), 100));

  return (
    <div className="flex items-center gap-4 px-4 py-3 bg-sol-base3 border-b border-sol-base1/10 last:border-b-0 hover:bg-sol-base2/40 transition-colors">
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="w-4 h-4 accent-sol-cyan rounded shrink-0"
      />
      <span className="text-sol-blue font-bold text-sm w-6 shrink-0">{rank}.</span>
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-sol-base02 truncate">{result.nazwa}</div>
        <div className="text-sm text-sol-base01 mt-0.5">
          <code className="bg-sol-base2 px-1.5 py-0.5 rounded text-xs text-sol-cyan">{result.indeks}</code>
          {result.jdmr_nazwa && (
            <span className="ml-2 text-sol-base1">{result.jdmr_nazwa}</span>
          )}
        </div>
      </div>
      <div className="shrink-0 w-44">
        <div className="flex items-center gap-2">
          <div className="flex-1 bg-sol-base2 rounded-full h-2">
            <div
              className="bg-sol-cyan h-2 rounded-full transition-all"
              style={{ width: `${scorePct}%` }}
            />
          </div>
          <span className="text-xs tabular-nums font-medium text-sol-base01 shrink-0">{(result.score * 100).toFixed(0)}%</span>
        </div>
      </div>
    </div>
  );
}
