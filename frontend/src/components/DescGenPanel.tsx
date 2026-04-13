import { useGenerateDescription } from '../api/search';
import type { SearchResult } from '../types';

interface Props {
  result: SearchResult;
  query: string;
  onDescriptionGenerated?: (description: string) => void;
}

export default function DescGenPanel({ result, query, onDescriptionGenerated }: Props) {
  const descGen = useGenerateDescription();

  const handleGenerate = () => {
    descGen.mutate(
      { nazwa: result.nazwa, indeks: result.indeks, query },
      {
        onSuccess: (data) => {
          if (!data.error && onDescriptionGenerated) {
            onDescriptionGenerated(data.description);
          }
        },
      },
    );
  };

  return (
    <div className="px-4 py-3 bg-sol-base2/60 border-t border-sol-cyan/20">
      <button
        onClick={handleGenerate}
        disabled={descGen.isPending}
        className="px-3 py-1.5 bg-sol-violet text-sol-base3 rounded-lg text-xs font-medium hover:opacity-85 disabled:opacity-50"
      >
        {descGen.isPending ? 'Generowanie...' : 'Generuj opis (Groq LLM)'}
      </button>
      {descGen.data && !descGen.data.error && (
        <div className="mt-2 p-3 bg-sol-base3 rounded border border-sol-base1/20 text-sm text-sol-base01">
          {descGen.data.description}
        </div>
      )}
      {descGen.data?.error && (
        <p className="mt-2 text-sm text-sol-red">{descGen.data.description}</p>
      )}
    </div>
  );
}
