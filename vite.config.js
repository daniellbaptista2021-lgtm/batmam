import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  root: 'static',
  build: {
    outDir: resolve(__dirname, 'static/dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        chat_js: resolve(__dirname, 'static/js/chat.js'),
        chat_css: resolve(__dirname, 'static/css/chat.css'),
      },
      output: {
        entryFileNames: 'js/[name].[hash].js',
        chunkFileNames: 'js/[name].[hash].js',
        assetFileNames: (info) => {
          if (info.name && info.name.endsWith('.css')) {
            return 'css/[name].[hash].css';
          }
          return 'assets/[name].[hash][extname]';
        },
      },
    },
    minify: 'esbuild',
    sourcemap: false,
  },
});
