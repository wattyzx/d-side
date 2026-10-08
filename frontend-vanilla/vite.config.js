import { fileURLToPath } from 'node:url';

function proxy() {
  return {
    target: 'http://127.0.0.1:8000',
    configure(server) {
      server.on('proxyReq', (outgoing, request) => {
        // Local comparison only: preserve the backend's existing trusted origin.
        // Do not rewrite requests from any other browser origin.
        if (request.headers.origin === 'http://localhost:5174') {
          outgoing.setHeader('Origin', 'http://localhost:5173');
        }
      });
    },
  };
}

export default {
  server: {
    port: 5174,
    strictPort: true,
    fs: { allow: [fileURLToPath(new URL('..', import.meta.url))] },
    proxy: { '/auth': proxy(), '/recommend': proxy(), '/wantlist': proxy() },
  },
};
