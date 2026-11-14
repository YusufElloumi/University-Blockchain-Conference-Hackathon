import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { PrivyProvider } from "@privy-io/react-auth";
import { createSolanaRpc, createSolanaRpcSubscriptions } from "@solana/kit";
import App from "./App";
import { RPC_URL } from "./chain";
import "./styles.css";

const appId = import.meta.env.VITE_PRIVY_APP_ID;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {appId ? (
      <PrivyProvider
        appId={appId}
        config={{
          // Email code only: no wallet buttons, no seed phrases.
          loginMethods: ["email"],
          appearance: { theme: "light", accentColor: "#e8590c" },
          embeddedWallets: {
            // Privy creates a Solana wallet behind the scenes the first time someone logs in.
            solana: { createOnLogin: "users-without-wallets" },
            // No wallet confirmation popups; our own button says what happens in plain words.
            showWalletUIs: false,
          },
          solana: {
            rpcs: {
              "solana:devnet": {
                rpc: createSolanaRpc(RPC_URL),
                rpcSubscriptions: createSolanaRpcSubscriptions(RPC_URL.replace(/^http/, "ws")),
              },
            },
          },
        }}
      >
        <App />
      </PrivyProvider>
    ) : (
      <p style={{ padding: 24 }}>Set VITE_PRIVY_APP_ID in the .env file at the repo root, then restart.</p>
    )}
  </StrictMode>,
);
