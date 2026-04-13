import { useState } from 'react';
import { useBulkSearch, useBulkDownload } from '../api/search';
import DropZone from '../components/DropZone';
import OptionsPanel from '../components/OptionsPanel';
import type { BulkResultRow } from '../types';

function ScoreBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(Math.round(score * 100), 100));
  const color =
    pct >= 70 ? 'bg-sol-green' : pct >= 40 ? 'bg-sol-yellow' : 'bg-sol-orange';

  return (
    <div className="flex items-center gap-2">
      <div className="w-20 bg-sol-base2 rounded-full h-1.5 shrink-0">
        <div className={`${color} h-1.5 rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-sol-base01">{pct}%</span>
    </div>
  );
}

function ScoreBadge({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${color}`}>
      {label}
      <span className="font-bold">{count}</span>
    </span>
  );
}

function scoreRowBg(score: number) {
  if (score >= 0.70) return 'bg-sol-green/5';
  if (score >= 0.40) return 'bg-sol-yellow/5';
  return 'bg-sol-orange/5';
}

export default function BulkSearchPage() {
  const [file, setFile] = useState<File | null>(null);
  const [rerank, setRerank] = useState(true);
  const [optionsOpen, setOptionsOpen] = useState(false);

  const bulk = useBulkSearch();
  const download = useBulkDownload();
  const rows: BulkResultRow[] = bulk.data?.results ?? [];

  const highCount  = rows.filter(r => r.score >= 0.70).length;
  const midCount   = rows.filter(r => r.score >= 0.40 && r.score < 0.70).length;
  const lowCount   = rows.filter(r => r.score < 0.40).length;

  const handleDownload = async () => {
    if (!file) return;
    const blob = await download.mutateAsync({ file, rerank });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'wyniki_indeksow.xlsx';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="w-full">
      <h2 className="text-2xl font-bold text-sol-base02 mb-6 text-center">
        Wyszukiwanie zbiorcze indeksów
      </h2>

      {/* Drop zone */}
      <DropZone file={file} onFile={setFile} />

      {/* Action bar */}
      {file && (
        <div className="flex items-center gap-3 mt-4">
          <button
            onClick={() => file && bulk.mutate({ file, rerank })}
            disabled={bulk.isPending}
            className="px-5 py-2.5 bg-sol-blue text-sol-base3 rounded-lg text-sm font-medium hover:opacity-85 disabled:opacity-50"
          >
            {bulk.isPending ? 'Przetwarzanie...' : 'Wyszukaj indeksy'}
          </button>
          {rows.length > 0 && (
            <button
              onClick={handleDownload}
              disabled={download.isPending}
              className="px-5 py-2.5 bg-sol-green text-sol-base3 rounded-lg text-sm font-medium hover:opacity-85 disabled:opacity-50"
            >
              {download.isPending ? 'Pobieranie...' : 'Pobierz wynik'}
            </button>
          )}
          <button
            onClick={() => setOptionsOpen(true)}
            className="px-3 py-2.5 border border-sol-base1/30 rounded-lg text-[26px] text-sol-base01 bg-sol-base3 hover:bg-sol-base2 transition-colors leading-none"
            title="Opcje wyszukiwania"
          >
            ⚙
          </button>
        </div>
      )}

      <OptionsPanel
        isOpen={optionsOpen}
        onClose={() => setOptionsOpen(false)}
        rerank={rerank}
        setRerank={setRerank}
        showTopK={false}
      />

      {bulk.isError && (
        <div className="p-4 bg-sol-red/10 text-sol-red rounded-lg mt-4 text-sm">
          Błąd: {(bulk.error as Error).message}
        </div>
      )}

      {/* Stats summary */}
      {rows.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mt-6 mb-3">
          <span className="text-sm text-sol-base01 mr-1">
            Łącznie: <strong className="text-sol-base02">{rows.length}</strong>
          </span>
          <span className="text-sol-base1 text-sm">·</span>
          <ScoreBadge label="Wysoka pewność:" count={highCount} color="bg-sol-green/15 text-sol-green" />
          <ScoreBadge label="Średnia:" count={midCount} color="bg-sol-yellow/15 text-sol-yellow" />
          <ScoreBadge label="Niska:" count={lowCount} color="bg-sol-orange/15 text-sol-orange" />
        </div>
      )}

      {/* Results table */}
      {rows.length > 0 && (
        <div className="rounded-lg border border-sol-base1/20 overflow-auto max-h-[60vh]">
          <table className="w-full text-sm border-collapse">
            <thead className="sticky top-0 z-10">
              <tr className="bg-sol-base2 border-b border-sol-base1/20">
                <th className="text-left px-4 py-3 text-xs font-semibold text-sol-base01 uppercase tracking-wide w-[35%]">
                  Opis materiału
                </th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-sol-base01 uppercase tracking-wide w-[15%]">
                  Indeks
                </th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-sol-base01 uppercase tracking-wide">
                  Nazwa materiału
                </th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-sol-base01 uppercase tracking-wide w-[20%]">
                  Prawdopodobieństwo poprawności
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr
                  key={i}
                  className="border-t border-sol-base1/10 hover:bg-sol-base2/50 transition-colors"
                >
                  <td className="px-4 py-3 bg-sol-base2/60 text-sol-base01 align-top leading-snug">
                    {row.opis_materialu}
                  </td>
                  <td className="px-4 py-3 align-top">
                    {row.indeks ? (
                      <code className="bg-sol-base2 px-1.5 py-0.5 rounded text-xs text-sol-cyan">
                        {row.indeks}
                      </code>
                    ) : (
                      <span className="text-sol-base1">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sol-base02 align-top">
                    {row.nazwa || <span className="text-sol-base1">—</span>}
                  </td>
                  <td className={`px-4 py-3 align-top ${scoreRowBg(row.score)}`}>
                    {row.score > 0 ? (
                      <ScoreBar score={row.score} />
                    ) : (
                      <span className="text-sol-base1 text-xs">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
