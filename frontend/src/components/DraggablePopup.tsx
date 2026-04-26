import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Lightweight draggable popup window. Used by ``NodePopupManager`` to
 * surface big-picture and subgraph node details without blocking the
 * underlying graph canvas.
 *
 * Drag is initiated from the title-bar; mousedown captures the cursor
 * offset, mousemove updates position until mouseup releases. The popup
 * is positioned absolutely against its closest positioned ancestor (or
 * the viewport when none exists).
 */

export interface DraggablePopupProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  initialPosition?: { x: number; y: number };
  zIndex?: number;
  /** Optional test id for the outer container. */
  testId?: string;
}

export function DraggablePopup({
  title,
  onClose,
  children,
  initialPosition = { x: 80, y: 80 },
  zIndex = 60,
  testId,
}: DraggablePopupProps) {
  const [position, setPosition] = useState(initialPosition);
  const [isDragging, setIsDragging] = useState(false);
  const dragOffset = useRef<{ dx: number; dy: number } | null>(null);

  const onMouseDown = useCallback(
    (event: React.MouseEvent) => {
      event.preventDefault();
      dragOffset.current = {
        dx: event.clientX - position.x,
        dy: event.clientY - position.y,
      };
      setIsDragging(true);
    },
    [position.x, position.y],
  );

  useEffect(() => {
    if (!isDragging) return;

    const onMouseMove = (event: MouseEvent) => {
      const offset = dragOffset.current;
      if (!offset) return;
      setPosition({
        x: event.clientX - offset.dx,
        y: event.clientY - offset.dy,
      });
    };
    const onMouseUp = () => {
      dragOffset.current = null;
      setIsDragging(false);
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [isDragging]);

  return (
    <div
      className="pointer-events-auto fixed flex w-[320px] max-w-[90vw] flex-col overflow-hidden rounded-lg border border-slate-700 bg-panel/95 text-ink shadow-2xl backdrop-blur"
      style={{ left: position.x, top: position.y, zIndex }}
      role="dialog"
      aria-label={title}
      data-testid={testId}
    >
      <header
        onMouseDown={onMouseDown}
        className={`flex items-center justify-between gap-3 border-b border-slate-700 bg-slate-800/80 px-3 py-2 select-none ${
          isDragging ? "cursor-grabbing" : "cursor-grab"
        }`}
      >
        <h3 className="truncate text-sm font-semibold">{title}</h3>
        <button
          type="button"
          onClick={onClose}
          aria-label={`Close ${title}`}
          className="shrink-0 rounded p-1 text-muted hover:bg-slate-700/60 hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
        >
          <svg
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M6 6l12 12M18 6l-12 12" />
          </svg>
        </button>
      </header>

      <div className="max-h-[60vh] flex-1 overflow-y-auto px-3 py-3 text-[12px] leading-relaxed text-slate-200">
        {children}
      </div>
    </div>
  );
}
