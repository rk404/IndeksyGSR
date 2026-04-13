import type { SearchResult } from '../types';
import ResultCard from './ResultCard';
import DescGenPanel from './DescGenPanel';

interface Props {
  results: SearchResult[];
  selected: Set<string>;
  onToggle: (indeks: string) => void;
  query: string;
  onDescriptionChange?: (indeks: string, description: string) => void;
}

export default function SearchResults({ results, selected, onToggle, query, onDescriptionChange }: Props) {
  if (results.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        Brak wyników. Spróbuj innego zapytania.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-sol-base1/20 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-4 px-4 py-2 bg-sol-base2 border-b border-sol-base1/20">
        <div className="w-4 shrink-0" />
        <div className="w-6 shrink-0" />
        <div className="flex-1 text-xs font-semibold text-sol-base01 uppercase tracking-wide">
          Nazwa / Indeks
        </div>
        <div className="shrink-0 w-44 text-xs font-semibold text-sol-base01 uppercase tracking-wide">
          Prawdopodobieństwo poprawności
        </div>
      </div>
      {results.map((r, i) => (
        <div key={r.indeks + i}>
          <ResultCard
            result={r}
            rank={i + 1}
            checked={selected.has(r.indeks)}
            onToggle={() => onToggle(r.indeks)}
          />
          {selected.has(r.indeks) && (
            <DescGenPanel
              result={r}
              query={query}
              onDescriptionGenerated={(desc) => onDescriptionChange?.(r.indeks, desc)}
            />
          )}
        </div>
      ))}
    </div>
  );
}
