/** Small line icons for the sidebar and buttons. Decorative: the label next to each one is what is announced. */
type IconProps = { className?: string };

const base = "h-9 w-9 flex-none";
const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round" } as const;

export const ShopIcon = ({ className = base }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
    <path d="M4 8h16l-1.2 11.2a2 2 0 0 1-2 1.8H7.2a2 2 0 0 1-2-1.8L4 8Z" />
    <path d="M8.5 8V6.5a3.5 3.5 0 0 1 7 0V8" />
  </svg>
);
export const ScannerIcon = ({ className = base }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
    <path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16" />
    <path d="M7 12h10" />
  </svg>
);
export const CartIcon = ({ className = base }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
    <path d="M3 4h2.2l2 11.2a1.5 1.5 0 0 0 1.5 1.3h8.6a1.5 1.5 0 0 0 1.5-1.1L20 8H6.2" />
    <circle cx="9.5" cy="20" r="1.3" />
    <circle cx="17" cy="20" r="1.3" />
  </svg>
);
export const HelpIcon = ({ className = base }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9.5a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.1-2.5 3.6M12 17.3v.2" />
  </svg>
);
export const SettingsIcon = ({ className = base }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 14.5a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3h0a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5h0a1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8v0a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1Z" />
  </svg>
);
export const CloseIcon = ({ className = "h-7 w-7" }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);
export const CheckIcon = ({ className = "h-7 w-7" }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke} strokeWidth={2.4}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </svg>
);
export const MirrorIcon = ({ className = "h-9 w-9" }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
    <rect x="6" y="2.5" width="12" height="17" rx="6" />
    <path d="M9 22h6M12 19.5V22" />
  </svg>
);
