export default {
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/auth': 'http://127.0.0.1:8000',
      '/recommend': 'http://127.0.0.1:8000',
      '/wantlist': 'http://127.0.0.1:8000',
    },
  },
};
