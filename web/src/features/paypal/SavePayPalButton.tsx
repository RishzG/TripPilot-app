export interface SavePayPalButtonProps {
  setupTokenPath: string;
  paymentTokenPath: string;
  onSaved: () => void;
  onFailed: (reason: 'cancelled' | 'error') => void;
}

/** Stub: replaced in the GREEN commit of plan 01-08. */
export function SavePayPalButton(_props: SavePayPalButtonProps) {
  return null;
}
