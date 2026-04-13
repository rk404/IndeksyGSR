interface Props {
  isOpen: boolean;
  onClose: () => void;
  topK?: number;
  setTopK?: (v: number) => void;
  rerank: boolean;
  setRerank: (v: boolean) => void;
  showTopK?: boolean;
}

export default function OptionsPanel({
  isOpen,
  onClose,
  topK,
  setTopK,
  rerank,
  setRerank,
  showTopK = true,
}: Props) {
  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-sol-base03/20 z-40"
          onClick={onClose}
        />
      )}

      {/* Drawer */}
      <div
        className={`fixed top-0 right-0 h-full w-72 bg-sol-base3 border-l border-sol-base1/20 shadow-xl z-50 flex flex-col transition-transform duration-200 ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-sol-base1/20">
          <h3 className="font-semibold text-sol-base02">Opcje wyszukiwania</h3>
          <button
            onClick={onClose}
            className="text-sol-base1 hover:text-sol-base01 text-xl leading-none"
          >
            ×
          </button>
        </div>

        <div className="flex-1 px-5 py-6 space-y-6">
          {showTopK && setTopK && topK !== undefined && (
            <div>
              <label className="block text-sm font-medium text-sol-base01 mb-2">
                Ilość wyników
              </label>
              <select
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
                className="w-full px-3 py-2 border border-sol-base1/30 rounded-lg text-sm bg-sol-base3 text-sol-base02"
              >
                <option value={5}>Top 5</option>
                <option value={10}>Top 10</option>
                <option value={20}>Top 20</option>
              </select>
            </div>
          )}

          <div>
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={rerank}
                onChange={(e) => setRerank(e.target.checked)}
                className="mt-0.5 w-4 h-4 accent-sol-cyan rounded shrink-0"
              />
              <div>
                <span className="block text-sm font-medium text-sol-base01">
                  Cross-encoder reranking
                </span>
                <span className="block text-xs text-sol-base1 mt-0.5">
                  Dokładniejsze wyniki, wolniejsze wyszukiwanie
                </span>
              </div>
            </label>
          </div>
        </div>
      </div>
    </>
  );
}
