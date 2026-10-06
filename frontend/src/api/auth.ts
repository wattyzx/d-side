import { session } from "../session.ts";
import { apiFetch, assertCurrentSession, SessionExpiredError } from "./http.ts";

export type Account = { authenticated: true; username: string };

export const discogsLoginUrl = "/auth/discogs/login";

export async function getAccount(): Promise<Account | null> {
  const revision = session.getSnapshot().revision;
  try {
    const response = await apiFetch("/auth/me", { cache: "no-store" }, {
      allowAnonymous: true, fallback: "Could not check your Discogs connection.",
    });
    const account: Account = await response.json();
    assertCurrentSession(revision);
    session.signIn();
    return account;
  } catch (error) {
    if (error instanceof SessionExpiredError) return null;
    assertCurrentSession(revision);
    throw error;
  }
}

export async function logout(): Promise<void> {
  await apiFetch("/auth/logout", { method: "POST" }, {
    fallback: "Could not sign out. Please try again.",
  });
  session.signOut();
}
