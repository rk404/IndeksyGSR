import { useState } from 'react';
import { useSearchByUrl, useSaveSelection } from '../api/search';
import SearchResults from '../components/SearchResults';
import SegmentForm from '../components/SegmentForm';
import OptionsPanel from '../components/OptionsPanel';
import type { SearchResult } from '../types';

export default function SearchByUrlPage() {
  const [url, setUrl] = useState('');
  const [topK, setTopK] = useState(10);
  const [rerank, setRerank] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [descriptions, setDescriptions] = useState<Record<string, string>>({});
  const [showPropose, setShowPropose] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);

  const search = useSearchByUrl();
  const save = useSaveSelection();

  const handleSearch = () => {
    if (!url.trim()) return;
    search.mutate({ url, top_k: topK, rerank });
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
      source: 'url',
      results: selectedResults,
      groq_descriptions: descriptions,
    });
  };

  return (
    <div className="w-full">
      <h2 className="text-2xl font-bold text-sol-base02 mb-6 text-center">
        Wyszukiwanie po URL sklepu
      </h2>

      <div className="flex gap-3 mb-6">
        <textarea
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), handleSearch())}
          placeholder="https://sklep.pl/produkt/..."
          rows={1}
          className="flex-1 px-4 py-2.5 border border-sol-base1/30 rounded-lg text-sm bg-sol-base3 text-sol-base02 placeholder:text-sol-base1 focus:ring-2 focus:ring-sol-cyan focus:border-sol-cyan resize-none overflow-hidden field-sizing-content min-h-[42px]"
        />
        <button
          onClick={handleSearch}
          disabled={search.isPending || !url.trim()}
          className="px-5 py-2.5 bg-sol-blue text-sol-base3 rounded-lg text-sm font-medium hover:opacity-85 disabled:opacity-50"
        >
          {search.isPending ? 'Scrapuję...' : 'Wyszukaj'}
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
          Błąd: {(search.error as Error).message}
        </div>
      )}

      {search.data?.scraped && (
        <details className="mb-6 bg-sol-base2 border border-sol-base1/20 rounded-lg">
          <summary className="px-4 py-3 text-sm font-medium text-sol-base01 cursor-pointer hover:text-sol-base02">
            Dane ze strony: {search.data.scraped.title || '(brak tytułu)'}
          </summary>
          <div className="px-4 pb-4 text-sm text-sol-base01 space-y-2">
            {search.data.scraped.price && <p><strong>Cena:</strong> {search.data.scraped.price}</p>}
            {Object.keys(search.data.scraped.specifications).length > 0 && (
              <div>
                <strong>Specyfikacja:</strong>
                <table className="mt-1 text-xs w-full">
                  <tbody>
                    {Object.entries(search.data.scraped.specifications).map(([k, v]) => (
                      <tr key={k} className="border-b border-sol-base1/10">
                        <td className="py-1 pr-3 font-medium text-sol-base1">{k}</td>
                        <td className="py-1">{v}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {search.data.scraped.description && (
              <div>
                <strong>Opis:</strong>
                <p className="mt-1 text-xs text-sol-base1 whitespace-pre-line">
                  {search.data.scraped.description.slice(0, 500)}
                </p>
              </div>
            )}
          </div>
        </details>
      )}

      {search.data && (
        <>
          <p className="text-sm text-sol-base01 mb-4">
            <strong className="text-sol-base02">{search.data.results.length}</strong> wyników · Zapytanie: <em>{search.data.query.slice(0, 100)}</em>
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
