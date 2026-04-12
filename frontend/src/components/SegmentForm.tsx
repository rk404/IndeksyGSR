import { useState, useEffect, useMemo } from 'react';
import { useSegments, useSuggest, usePropose } from '../api/segments';
import type { SearchResult } from '../types';

interface Props {
  query: string;
  results: SearchResult[];
  onSaved?: () => void;
}

export default function SegmentForm({ query, results, onSaved }: Props) {
  const { data: tree, isLoading: treeLoading } = useSegments();
  const suggest = useSuggest();
  const propose = usePropose();

  const [sel1, setSel1] = useState('');
  const [sel2, setSel2] = useState('');
  const [sel3, setSel3] = useState('');
  const [sel4, setSel4] = useState('0');
  const [sel5, setSel5] = useState('0');
  const [sel6, setSel6] = useState('0');
  const [nazwa, setNazwa] = useState('');

  useEffect(() => {
    if (query) suggest.mutate({ query, top_n: 1 });
  }, [query]);

  useEffect(() => {
    if (suggest.data && suggest.data.length > 0) {
      const best = suggest.data[0];
      setSel1(best.seg1_text);
      setSel2(best.seg2_text);
      setSel3(best.seg3_text);
    }
  }, [suggest.data]);

  useEffect(() => {
    if (results.length > 0) {
      const top = results[0] as Record<string, unknown>;
      setSel4((top.seg4 as string) || '0');
      setSel5((top.seg5 as string) || '0');
      setSel6((top.seg6 as string) || '0');
    }
  }, [results]);

  const pos1Opts = useMemo(() => {
    if (!tree) return [];
    return [...new Set(Object.values(tree.pos1))].sort();
  }, [tree]);

  const seg1SlitId = useMemo(() => {
    if (!tree || !sel1) return null;
    return Object.entries(tree.pos1).find(([, v]) => v === sel1)?.[0] ?? null;
  }, [tree, sel1]);

  const pos2Opts = useMemo(() => {
    if (!tree || !seg1SlitId) return [];
    const children = tree.pos2_by_parent[seg1SlitId] || [];
    return [...new Set(children.map(([, t]) => t))].sort();
  }, [tree, seg1SlitId]);

  const seg2SlitId = useMemo(() => {
    if (!tree || !seg1SlitId || !sel2) return null;
    const children = tree.pos2_by_parent[seg1SlitId] || [];
    return children.find(([, t]) => t === sel2)?.[0]?.toString() ?? null;
  }, [tree, seg1SlitId, sel2]);

  const pos3Opts = useMemo(() => {
    if (!tree || !seg2SlitId) return [];
    const children = tree.pos3_by_parent[seg2SlitId] || [];
    return [...new Set(children.map(([, t]) => t))].sort();
  }, [tree, seg2SlitId]);

  const seg3SlitId = useMemo(() => {
    if (!tree || !seg2SlitId || !sel3) return null;
    const children = tree.pos3_by_parent[seg2SlitId] || [];
    return children.find(([, t]) => t === sel3)?.[0]?.toString() ?? null;
  }, [tree, seg2SlitId, sel3]);

  const kod1 = tree && seg1SlitId ? tree.pos1_kod[seg1SlitId] || '' : '';
  const kod2 = tree && seg2SlitId ? tree.pos2_kod[seg2SlitId] || '' : '';
  const kod3 = tree && seg3SlitId ? tree.pos3_kod[seg3SlitId] || '' : '';
  const indexCode = `${kod1}-${kod2}-${kod3}-${sel4}-${sel5}-${sel6}-`;

  useEffect(() => {
    const parts = [sel1, sel2, sel3, sel4, sel5, sel6].filter((s) => s && s !== '0');
    setNazwa(parts.join(' ').toUpperCase());
  }, [sel1, sel2, sel3, sel4, sel5, sel6]);

  const handleSubmit = () => {
    propose.mutate(
      { query, seg1: sel1, seg2: sel2, seg3: sel3, seg4: sel4, seg5: sel5, seg6: sel6, kod1, kod2, kod3, nazwa, indeks: indexCode },
      { onSuccess: () => onSaved?.() },
    );
  };

  if (treeLoading) return <div className="text-sol-base1 py-4">Ładowanie drzewa segmentów...</div>;
  if (!tree) return null;

  return (
    <div className="bg-sol-base3 border border-sol-base1/20 rounded-lg p-6 space-y-6">
      <h3 className="text-lg font-semibold text-sol-base02">Propozycja nowego indeksu</h3>

      {suggest.isPending && <p className="text-sm text-sol-base1">Szukam pasujących segmentów...</p>}

      <div>
        <p className="text-sm font-medium text-sol-base01 mb-3">Pozycje 1-3 (hierarchiczne)</p>
        <div className="grid grid-cols-3 gap-4">
          <Select label="Typ (poz. 1)" value={sel1} options={pos1Opts} onChange={(v) => { setSel1(v); setSel2(''); setSel3(''); }} />
          <Select label="Grupa (poz. 2)" value={sel2} options={pos2Opts} onChange={(v) => { setSel2(v); setSel3(''); }} />
          <Select label="Podgrupa (poz. 3)" value={sel3} options={pos3Opts} onChange={setSel3} />
        </div>
      </div>

      <div>
        <p className="text-sm font-medium text-sol-base01 mb-3">Pozycje 4-6 (kody techniczne)</p>
        <div className="grid grid-cols-3 gap-4">
          <Select label="Cecha główna (poz. 4)" value={sel4} options={['0', ...tree.pos4_values]} onChange={setSel4} />
          <Select label="Materiał (poz. 5)" value={sel5} options={['0', ...tree.pos5_values]} onChange={setSel5} />
          <Select label="Odbiór (poz. 6)" value={sel6} options={['0', ...tree.pos6_values]} onChange={setSel6} />
        </div>
      </div>

      <div className="bg-sol-base2 rounded-lg px-4 py-3">
        <span className="text-sm text-sol-base1">Kod indeksu: </span>
        <code className="font-mono font-semibold text-sol-base02">{indexCode}</code>
      </div>

      <div>
        <label className="block text-sm font-medium text-sol-base01 mb-1">Nazwa</label>
        <input
          type="text"
          value={nazwa}
          onChange={(e) => setNazwa(e.target.value)}
          className="w-full px-3 py-2 border border-sol-base1/30 rounded-lg text-sm bg-sol-base3 text-sol-base02 focus:ring-2 focus:ring-sol-cyan focus:border-sol-cyan"
        />
      </div>

      <button
        onClick={handleSubmit}
        disabled={propose.isPending || !sel1 || !sel2 || !sel3}
        className="px-4 py-2 bg-sol-blue text-sol-base3 rounded-lg text-sm font-medium hover:opacity-85 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {propose.isPending ? 'Zapisywanie...' : 'Zapisz propozycję'}
      </button>

      {propose.isSuccess && (
        <p className="text-sm text-sol-green">Propozycja zapisana w Firestore.</p>
      )}
      {propose.isError && (
        <p className="text-sm text-sol-red">Błąd zapisu: {(propose.error as Error).message}</p>
      )}
    </div>
  );
}

function Select({ label, value, options, onChange }: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="block text-xs text-sol-base1 mb-1">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 border border-sol-base1/30 rounded-lg text-sm bg-sol-base3 text-sol-base02 focus:ring-2 focus:ring-sol-cyan focus:border-sol-cyan"
      >
        <option value="">—</option>
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </div>
  );
}
