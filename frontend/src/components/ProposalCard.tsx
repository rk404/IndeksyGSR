import type { ProposalItem } from '../types';

const statusStyles: Record<string, { bg: string; text: string; label: string }> = {
  proposed: { bg: 'bg-sol-yellow/15', text: 'text-sol-yellow', label: 'oczekuje' },
  approved: { bg: 'bg-sol-green/15', text: 'text-sol-green', label: 'zatwierdzone' },
  rejected: { bg: 'bg-sol-red/15', text: 'text-sol-red', label: 'odrzucone' },
};

interface Props {
  proposal: ProposalItem;
  onApprove?: () => void;
  onReject?: () => void;
  approving?: boolean;
  rejecting?: boolean;
}

export default function ProposalCard({ proposal, onApprove, onReject, approving, rejecting }: Props) {
  const style = statusStyles[proposal.status] || statusStyles.proposed;
  const segments = [proposal.seg1, proposal.seg2, proposal.seg3, proposal.seg4, proposal.seg5, proposal.seg6]
    .filter((s) => s && s !== '0')
    .join(' / ');

  return (
    <div className="flex items-start gap-4 p-4 bg-sol-base3 rounded-lg border border-sol-base1/20">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${style.bg} ${style.text}`}>
            {style.label}
          </span>
          <span className="font-semibold text-sol-base02 truncate">{proposal.nazwa}</span>
        </div>
        <div className="text-sm text-sol-base01">
          Segmenty: <code className="bg-sol-base2 px-1 py-0.5 rounded text-xs">{segments}</code>
        </div>
        <div className="text-xs text-sol-base1 mt-1">
          Zapytanie: <em>{proposal.query}</em> · {proposal.proposed_at?.slice(0, 10)}
        </div>
      </div>

      {proposal.status === 'proposed' && (
        <div className="flex gap-2 shrink-0">
          <button
            onClick={onApprove}
            disabled={approving}
            className="px-3 py-1.5 bg-sol-green text-sol-base3 rounded-lg text-xs font-medium hover:opacity-80 disabled:opacity-50"
          >
            {approving ? '...' : 'Zatwierdź'}
          </button>
          <button
            onClick={onReject}
            disabled={rejecting}
            className="px-3 py-1.5 bg-sol-red text-sol-base3 rounded-lg text-xs font-medium hover:opacity-80 disabled:opacity-50"
          >
            {rejecting ? '...' : 'Odrzuć'}
          </button>
        </div>
      )}

      {proposal.status === 'approved' && (
        <code className="text-xs text-sol-base1 shrink-0">PROP-{proposal.id.slice(0, 8).toUpperCase()}</code>
      )}
    </div>
  );
}
