import { useEffect } from "react";
import catPicture from "./assets/withdraw.png";

/** "Withdraw": there is nothing to withdraw. Devnet USDC is demo money and stays inside the app. */
export default function WithdrawNote({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="intro-backdrop" onClick={onClose}>
      <div className="intro withdraw" role="dialog" aria-modal="true" aria-labelledby="withdraw-title" onClick={(e) => e.stopPropagation()}>
        <button className="intro-close" onClick={onClose} aria-label="Close">
          ✕
        </button>
        <img className="withdraw-pic" src={catPicture} alt="A cat sticking its tongue out" />
        <h2 id="withdraw-title" className="intro-title">
          Nice try
        </h2>
        <p className="withdraw-text">This is a demo. Devnet USDC has no real value and stays inside the app.</p>
        <button className="primary" onClick={onClose} autoFocus>
          Got it
        </button>
      </div>
    </div>
  );
}
