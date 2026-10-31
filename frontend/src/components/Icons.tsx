// Tiny inline icon set (stroke icons, currentColor) — no icon dependency.
import type { ReactNode } from "react";

function Icon({ children, size = 18 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const SidebarIcon = () => (
  <Icon>
    <rect x="3" y="4" width="18" height="16" rx="3" />
    <path d="M9 4v16" />
  </Icon>
);
export const PlusIcon = () => (
  <Icon>
    <path d="M12 5v14M5 12h14" />
  </Icon>
);
export const SendIcon = () => (
  <Icon>
    <path d="M12 19V5M5 12l7-7 7 7" />
  </Icon>
);
export const StopIcon = () => (
  <Icon>
    <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" />
  </Icon>
);
export const SlidersIcon = () => (
  <Icon>
    <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
    <circle cx="16" cy="7" r="2" />
    <circle cx="8" cy="17" r="2" />
  </Icon>
);
export const ChevronIcon = () => (
  <Icon size={16}>
    <path d="m9 6 6 6-6 6" />
  </Icon>
);
export const CheckIcon = () => (
  <Icon size={16}>
    <path d="m5 12 5 5 9-10" />
  </Icon>
);
export const WarnIcon = () => (
  <Icon size={16}>
    <path d="M12 4 3 20h18L12 4zM12 10v4M12 17.5v.01" />
  </Icon>
);
export const DownloadIcon = () => (
  <Icon size={16}>
    <path d="M12 4v11M7 11l5 5 5-5M5 20h14" />
  </Icon>
);
export const LogoutIcon = () => (
  <Icon size={16}>
    <path d="M10 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4M14 8l4 4-4 4M18 12H9" />
  </Icon>
);

/** The brand mark: three bars, a nod to an equaliser. */
export const Mark = ({ size = 22 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
    <rect x="3" y="9" width="4" height="12" rx="2" fill="currentColor" opacity=".55" />
    <rect x="10" y="3" width="4" height="18" rx="2" fill="currentColor" />
    <rect x="17" y="12" width="4" height="9" rx="2" fill="currentColor" opacity=".8" />
  </svg>
);
