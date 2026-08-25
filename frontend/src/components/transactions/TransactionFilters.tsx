import { Search, SlidersHorizontal } from 'lucide-react';
import './TransactionFilters.css';

interface TransactionFiltersProps {
  statusFilter: string;
  setStatusFilter: (status: string) => void;
  searchTerm: string;
  setSearchTerm: (term: string) => void;
}

export default function TransactionFilters({
  statusFilter,
  setStatusFilter,
  searchTerm,
  setSearchTerm
}: TransactionFiltersProps) {
  const statuses = [
    { label: 'ALL RECORDS', value: 'ALL' },
    { label: 'SUCCESS', value: 'SUCCESS' },
    { label: 'PENDING', value: 'PENDING' },
    { label: 'FAILED', value: 'FAILED' }
  ];

  return (
    <div className="transaction-filters-container animate-fade-in">
      {/* Search Input */}
      <div className="search-input-wrapper">
        <Search className="search-icon" />
        <input
          type="text"
          placeholder="Search by Razorpay Order ID, PR ID, or Transaction ID..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="search-input font-mono"
        />
      </div>

      {/* Filter Tabs */}
      <div className="filter-controls">
        <div className="filter-label-wrapper">
          <SlidersHorizontal className="filter-icon" />
          <span className="font-mono text-dimmed">STATUS:</span>
        </div>
        <div className="filter-tabs">
          {statuses.map((status) => {
            let btnClass = 'filter-tab-btn font-mono';
            if (statusFilter === status.value) {
              btnClass += ' active';
              if (status.value === 'SUCCESS') btnClass += ' active-success';
              if (status.value === 'PENDING') btnClass += ' active-pending';
              if (status.value === 'FAILED') btnClass += ' active-failed';
            }
            return (
              <button
                key={status.value}
                onClick={() => setStatusFilter(status.value)}
                className={btnClass}
              >
                {status.label}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
