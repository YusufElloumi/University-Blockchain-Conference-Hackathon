import { X } from "lucide-react";
import catPicture from "./assets/withdraw.png";
import { useEscape } from "./ui";

/** "Withdraw": there is nothing to withdraw. Devnet USDC is demo money and stays inside the app. */
export default function WithdrawNote({ onClose }: { onClose: () => void }) {
  useEscape(onClose);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal modal-withdraw"
        role="dialog"
        aria-modal="true"
        aria-labelledby="withdraw-title"
        onClick={(e) => e.stopPropagation()}
      >
        <button className="icon-btn modal-close" onClick={onClose} aria-label="Close">
          <X size={16} aria-hidden />
        </button>
        <img className="withdraw-pic" src={catPicture} alt="A cat sticking its tongue out" />
        <h2 id="withdraw-title" className="modal-title">
          Nice <em className="serif">try.</em>
        </h2>
        <div className="modal-body">
          <p>This is a demo. Devnet USDC has no real value and stays inside the app.</p>
        </div>
        <button className="btn btn-primary btn-block btn-lg" onClick={onClose} autoFocus>
          Got it
        </button>
      </div>
    </div>
  );
}
