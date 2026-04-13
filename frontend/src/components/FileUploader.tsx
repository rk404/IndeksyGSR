import { useRef } from 'react';

interface Props {
  onFile: (file: File) => void;
  accept?: string;
  label?: string;
}

export default function FileUploader({ onFile, accept = '.xlsx', label = 'Wybierz plik Excel' }: Props) {
  const ref = useRef<HTMLInputElement>(null);

  return (
    <div>
      <input
        ref={ref}
        type="file"
        accept={accept}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
        }}
        className="hidden"
      />
      <button
        onClick={() => ref.current?.click()}
        className="px-4 py-2 border-2 border-dashed border-sol-base1/40 rounded-lg text-sm text-sol-base01 hover:border-sol-cyan hover:text-sol-cyan transition-colors"
      >
        {label}
      </button>
    </div>
  );
}
