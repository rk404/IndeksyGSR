import { useState } from 'react';
import { useProposals, useApproveProposal, useRejectProposal } from '../api/segments';
import ProposalCard from '../components/ProposalCard';

export default function ProposalsPage() {
  const [statusFilter, setStatusFilter] = useState<string>('');
  const { data: proposals, isLoading, refetch } = useProposals(statusFilter || undefined);
  const approve = useApproveProposal();
  const reject = useRejectProposal();

  const handleApprove = (id: string) => {
    approve.mutate(id, { onSuccess: () => refetch() });
  };

  const handleReject = (id: string) => {
    reject.mutate(id, { onSuccess: () => refetch() });
  };

  return (
    <div className="w-full">
      <h2 className="text-2xl font-bold text-sol-base02 mb-6 text-center">Propozycje nowych indeksów</h2>

      <div className="flex items-center gap-4 mb-6">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-3 py-2 border border-sol-base1/30 rounded-lg text-sm bg-sol-base3 text-sol-base01"
        >
          <option value="">Wszystkie</option>
          <option value="proposed">Oczekujące</option>
          <option value="approved">Zatwierdzone</option>
          <option value="rejected">Odrzucone</option>
        </select>
        {proposals && (
          <span className="text-sm text-sol-base1">{proposals.length} propozycji</span>
        )}
      </div>

      {isLoading && <p className="text-sol-base1">Ładowanie...</p>}

      {proposals && proposals.length === 0 && (
        <div className="text-center py-12 text-sol-base1">
          Brak propozycji. Użyj wyszukiwania i kliknij "zaproponuj nowy indeks".
        </div>
      )}

      <div className="space-y-3">
        {proposals?.map((p) => (
          <ProposalCard
            key={p.id}
            proposal={p}
            onApprove={() => handleApprove(p.id)}
            onReject={() => handleReject(p.id)}
            approving={approve.isPending && approve.variables === p.id}
            rejecting={reject.isPending && reject.variables === p.id}
          />
        ))}
      </div>
    </div>
  );
}
