import { useState } from 'react';
import { useSearch, useSaveSelection } from '../api/search';
import SearchResults from '../components/SearchResults';
import SegmentForm from '../components/SegmentForm';
import OptionsPanel from '../components/OptionsPanel';
import type { SearchResult } from '../types';

export default function SearchPage() {
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState(10);
  const [rerank, setRerank] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [descriptions, setDescriptions] = useState<Record<string, string>>({});
  const [showPropose, setShowPropose] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);

  const search = useSearch();
  const save = useSaveSelection();

  const handleSearch = () => {
    if (!query.trim()) return;
    search.mutate({ query, top_k: topK, rerank });
    setSelected(new Set());
    setDescriptions({});
    setShowPropose(false);
  };

  const toggleSelection = (indeks: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(indeks)) next.delete(indeks);
      else next.add(indeks);
      return next;
    });
  };

  const selectedResults: SearchResult[] =
    search.data?.results.filter((r) => selected.has(r.indeks)) ?? [];

  const handleSave = () => {
    if (!selectedResults.length || !search.data) return;
    save.mutate({
      query: search.data.query,
      source: 'text',
      results: selectedResults,
      groq_descriptions: descriptions,
    });
  };

  return (
    <div className="w-full">
      <h2 className="text-2xl font-bold text-sol-base02 mb-6 text-center">
        Wyszukiwanie semantyczne indeksów
      </h2>

      <div className="flex gap-3 mb-6">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), handleSearch())}
          placeholder="np. śruby M20 ocynkowane ogniowo"
          rows={1}
          className="flex-1 px-4 py-2.5 border border-sol-base1/30 rounded-lg text-sm bg-sol-base3 text-sol-base02 placeholder:text-sol-base1 focus:ring-2 focus:ring-sol-cyan focus:border-sol-cyan resize-none overflow-hidden field-sizing-content min-h-[42px]"
        />
        <button
          onClick={handleSearch}
          disabled={search.isPending || !query.trim()}
          className="px-5 py-2.5 bg-sol-blue text-sol-base3 rounded-lg text-sm font-medium hover:opacity-85 disabled:opacity-50"
        >
          {search.isPending ? 'Szukam...' : 'Szukaj'}
        </button>
        <button
          onClick={() => setOptionsOpen(true)}
          className="px-3 py-2.5 border border-sol-base1/30 rounded-lg text-[26px] text-sol-base01 bg-sol-base3 hover:bg-sol-base2 transition-colors leading-none"
          title="Opcje wyszukiwania"
        >
          ⚙
        </button>
      </div>

      <OptionsPanel
        isOpen={optionsOpen}
        onClose={() => setOptionsOpen(false)}
        topK={topK}
        setTopK={setTopK}
        rerank={rerank}
        setRerank={setRerank}
      />

      {search.isError && (
        <div className="p-4 bg-sol-red/10 text-sol-red rounded-lg mb-4 text-sm">
          Błąd wyszukiwania: {(search.error as Error).message}
        </div>
      )}

      {search.data && (
        <>
          <p className="text-sm text-sol-base01 mb-4">
            <strong className="text-sol-base02">{search.data.results.length}</strong> wyników dla: <em>{search.data.query}</em>
          </p>

          <SearchResults
            results={search.data.results}
            selected={selected}
            onToggle={toggleSelection}
            query={search.data.query}
            onDescriptionChange={(indeks, desc) =>
              setDescriptions((prev) => ({ ...prev, [indeks]: desc }))
            }
          />

          {selectedResults.length > 0 && (
            <div className="mt-4">
              <button
                onClick={handleSave}
                disabled={save.isPending}
                className="px-4 py-2 bg-sol-green text-sol-base3 rounded-lg text-sm font-medium hover:opacity-85 disabled:opacity-50"
              >
                {save.isPending ? 'Zapisywanie...' : `Zapisz zaznaczone (${selectedResults.length})`}
              </button>
              {save.isSuccess && (
                <span className="ml-3 text-sm text-sol-green">Zapisano do Firestore.</span>
              )}
            </div>
          )}

          <div className="mt-6 border-t border-sol-base1/20 pt-4">
            <button
              onClick={() => setShowPropose((v) => !v)}
              className="text-sm text-sol-orange hover:text-sol-red font-medium"
            >
              {showPropose ? 'Ukryj formularz' : 'Żadna odpowiedź nie jest prawidłowa — zaproponuj nowy indeks'}
            </button>
            {showPropose && (
              <div className="mt-4">
                <SegmentForm query={search.data.query} results={search.data.results} />
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
