import { useRef, useState } from 'react';

interface Props {
  file: File | null;
  onFile: (file: File) => void;
}

export default function DropZone({ file, onFile }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) onFile(dropped);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0];
    if (picked) onFile(picked);
  };

  const active = dragging || !!file;

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`
        w-full cursor-pointer rounded-xl border-2 border-dashed px-6 py-10
        flex flex-col items-center justify-center gap-3 transition-colors select-none
        ${active
          ? 'border-sol-cyan bg-sol-cyan/8 text-sol-cyan'
          : 'border-sol-base1/40 bg-sol-base2/40 text-sol-base1 hover:border-sol-cyan/60 hover:bg-sol-cyan/4'
        }
      `}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".xlsx"
        className="hidden"
        onChange={handleChange}
      />

      {file ? (
        <>
          <span className="text-3xl">✓</span>
          <div className="text-center">
            <p className="font-semibold text-sm">{file.name}</p>
            <p className="text-xs mt-0.5 opacity-70">Kliknij, aby zmienić plik</p>
          </div>
        </>
      ) : (
        <>
          <span className="text-3xl">📄</span>
          <div className="text-center">
            <p className="font-medium text-sm">
              Przeciągnij plik <code className="bg-sol-base2 px-1 py-0.5 rounded text-sol-cyan text-xs">.xlsx</code> lub kliknij, aby wybrać
            </p>
            <p className="text-xs mt-1 opacity-70">
              Wymagana kolumna: <code className="text-sol-cyan">opis_materialu</code>
            </p>
          </div>
        </>
      )}
    </div>
  );
}
