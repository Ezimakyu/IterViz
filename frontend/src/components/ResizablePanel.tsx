import { useState, useRef, useCallback, useEffect, type ReactNode } from "react";

interface ResizablePanelProps {
  children: ReactNode;
  defaultWidth: number;
  minWidth: number;
  maxWidth: number;
  side: "left" | "right";
  title: string;
  isOpen: boolean;
  onToggle: () => void;
  testId?: string;
}

export function ResizablePanel({
  children,
  defaultWidth,
  minWidth,
  maxWidth,
  side,
  title,
  isOpen,
  onToggle,
  testId,
}: ResizablePanelProps) {
  const [width, setWidth] = useState(defaultWidth);
  const isResizing = useRef(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isResizing.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (!isResizing.current || !panelRef.current) return;

      const rect = panelRef.current.getBoundingClientRect();
      let newWidth: number;

      if (side === "right") {
        newWidth = rect.right - e.clientX;
      } else {
        newWidth = e.clientX - rect.left;
      }

      newWidth = Math.max(minWidth, Math.min(maxWidth, newWidth));
      setWidth(newWidth);
    },
    [side, minWidth, maxWidth]
  );

  const handleMouseUp = useCallback(() => {
    isResizing.current = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  }, []);

  useEffect(() => {
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [handleMouseMove, handleMouseUp]);

  if (!isOpen) {
    return (
      <button
        onClick={onToggle}
        className={`
          flex h-full w-8 shrink-0 items-center justify-center
          border-slate-800 bg-panel text-muted
          hover:bg-slate-800 hover:text-ink transition-colors
          ${side === "right" ? "border-l" : "border-r"}
        `}
        title={`Show ${title}`}
        data-testid={testId ? `${testId}-toggle` : undefined}
      >
        <span className="writing-mode-vertical text-xs font-medium uppercase tracking-widest">
          {title}
        </span>
        <ChevronIcon direction={side === "right" ? "left" : "right"} className="mt-2" />
      </button>
    );
  }

  return (
    <div
      ref={panelRef}
      className={`
        relative flex h-full shrink-0 flex-col
        border-slate-800 bg-panel
        ${side === "right" ? "border-l" : "border-r"}
      `}
      style={{ width }}
      data-testid={testId}
    >
      {/* Resize handle */}
      <div
        onMouseDown={handleMouseDown}
        className={`
          absolute top-0 h-full w-1 cursor-col-resize
          hover:bg-sky-500/50 active:bg-sky-500/70
          transition-colors z-10
          ${side === "right" ? "left-0 -translate-x-1/2" : "right-0 translate-x-1/2"}
        `}
      />

      {/* Header with close button */}
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">
          {title}
        </h2>
        <button
          onClick={onToggle}
          className="rounded p-1 text-muted hover:bg-slate-700 hover:text-ink transition-colors"
          title={`Hide ${title}`}
        >
          <CloseIcon />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {children}
      </div>
    </div>
  );
}

function CloseIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function ChevronIcon({
  direction,
  className = "",
}: {
  direction: "left" | "right";
  className?: string;
}) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      {direction === "left" ? (
        <polyline points="15 18 9 12 15 6" />
      ) : (
        <polyline points="9 18 15 12 9 6" />
      )}
    </svg>
  );
}
