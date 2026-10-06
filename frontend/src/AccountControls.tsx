import { useState } from "react";
import { useMutation, type UseQueryResult } from "@tanstack/react-query";
import { discogsLoginUrl, logout, type Account } from "./api/auth";

const loginErrors: Record<string, string> = {
  incomplete: "Discogs login was cancelled or incomplete. Please try again.",
  expired: "Your login expired or did not match this browser. Please try again.",
  used: "This login has already been used. Please try again.",
  provider: "Could not connect with Discogs. Please try again.",
};

export default function AccountControls({ busy, account, sessionExpired }: {
  busy: boolean;
  account: UseQueryResult<Account | null, Error>;
  sessionExpired: boolean;
}) {
  const [loginError] = useState(() => {
    const code = new URLSearchParams(window.location.search).get("auth_error");
    return code ? loginErrors[code] ?? "Could not connect with Discogs. Please try again." : "";
  });
  const signOut = useMutation({
    mutationFn: logout,
  });

  return (
    <div className="account-controls" aria-label="Discogs account">
      {account.isPending ? <span role="status">Checking your connection…</span>
        : account.data ? <>
          <span>Connected as <strong>{account.data.username}</strong></span>
          <button type="button" onClick={() => signOut.mutate()} disabled={busy || signOut.isPending}>
            {signOut.isPending ? "Signing out…" : "Sign out"}
          </button>
        </> : <a className="connect-button" href={discogsLoginUrl}>Connect with Discogs</a>}
      {(account.isError || signOut.isError || loginError) && (
        <p className="account-error" role="alert">
          {account.error?.message || signOut.error?.message || loginError}
        </p>
      )}
      {sessionExpired && <p className="account-error" role="status">
        Your session expired. Connect with Discogs again to continue.
      </p>}
      {account.isError && <button type="button" onClick={() => void account.refetch()}>Retry</button>}
    </div>
  );
}
