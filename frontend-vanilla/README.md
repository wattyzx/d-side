# Vanilla frontend experiment

Plain HTML, CSS, and DOM JavaScript, with a minimal monochrome layout.
No React runtime or UI library. This is a client-rendered alternative, not
server-rendered HTML: recommendations still arrive through the existing stream.

Keep `./run.sh` running in one terminal. In another terminal at the project root:

```sh
npm run dev --prefix frontend-vanilla
```

Open **http://localhost:5174**. React remains at http://localhost:5173.
This experiment uses the Vite installation already in `frontend/node_modules`,
so no additional installation is needed after the normal project setup.

## Login and comparison

Connect with Discogs; the backend's existing OAuth callback returns to React on
port 5173. Then return to port 5174 and click **Refresh connection** (or reload).
Use `localhost` for both. Cookies are shared across ports, so signing out in one
frontend signs out the account for both. Avoid running searches in both tabs at
once: the backend allows one active search per account.

The local Vite proxy rewrites only an Origin of `http://localhost:5174` to
`http://localhost:5173`, which the unchanged backend already trusts. This is
development configuration; production should serve the chosen frontend and API
on the same origin. If your backend uses a custom FRONTEND_URL, adjust this
development mapping to its trusted local origin.

## Shared code and checks

The app reuses the existing framework-independent TypeScript modules in
`frontend/src/api/` and `frontend/src/session.ts`. Vite transpiles them. The
session module's TanStack import is type-only and adds no runtime dependency.
Changes to these shared modules affect both frontends.

```sh
npm run test --prefix frontend-vanilla
npm run build --prefix frontend-vanilla
```

The test command runs the existing API/session tests. Manually compare login,
streamed results, cancellation, search more, wantlist saves, logout, and a narrow
browser window. Production serving still selects the original React build;
this experiment does not change that setting.
