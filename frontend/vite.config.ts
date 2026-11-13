import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
export default defineConfig(({ mode, command }) => {
  const demo = mode === "demo";
  const previewProxy: Record<string, string> = demo
    ? {}
    : { "/api": "http://127.0.0.1:8000" };
  return {
    base: demo ? "/kefuagent/" : "/",
    plugins: [
      react(),
      tailwindcss(),
      {
        name: "kefu-delivery",
        enforce: "pre",
        // This is a browser-only SPA. Supply our own empty boundary marker instead
        // of redistributing client-only, whose release omits its license notice.
        resolveId(source) {
          if (source === "client-only") return "\0kefu-browser-boundary";
        },
        load(id) {
          if (id === "\0kefu-browser-boundary") return "export {};";
        },
        transformIndexHtml(html) {
          return demo && command === "build"
            ? html.replace(
                "<head>",
                "<head><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'self'; connect-src 'none'; script-src 'self'; style-src 'self' 'sha256-38RhXrc7EdReTKsOm23ZPOCUgniTUUcjky8QOOrQx6o='; img-src 'self' data:; font-src 'self'; base-uri 'none'; form-action 'none';\">",
              )
            : html;
        },
        generateBundle(_options, bundle) {
          const modules = [...this.getModuleIds()];
          if (
            modules.some((id) =>
              id.replaceAll("\\", "/").includes("/node_modules/client-only/"),
            )
          )
            throw new Error("Do not redistribute the client-only package");
          for (const chunk of Object.values(bundle)) {
            if (
              chunk.type === "chunk" &&
              Object.keys(chunk.modules).some((id) =>
                demo
                  ? id.endsWith("/adapters/api.ts")
                  : id.endsWith("/adapters/demo.ts") ||
                    id.endsWith("/adapters/demo-data.ts"),
              )
            )
              throw new Error(
                demo
                  ? "Demo must not contain the network adapter"
                  : "Production must not contain fictional Demo data",
              );
          }
          const source = readFileSync(
            new URL(demo ? "../src/support_agent/web/widget-demo.js" : "../src/support_agent/web/widget.js", import.meta.url),
            "utf8",
          );
          this.emitFile({ type: "asset", fileName: "widget.js", source });
          this.emitFile({
            type: "asset",
            fileName: "THIRD_PARTY_NOTICES.txt",
            source: readFileSync(
              new URL("./THIRD_PARTY_NOTICES.txt", import.meta.url),
              "utf8",
            ),
          });
        },
      },
    ],
    resolve: {
      alias: {
        "@adapter": fileURLToPath(
          new URL(
            demo ? "./src/adapters/demo.ts" : "./src/adapters/api.ts",
            import.meta.url,
          ),
        ),
      },
    },
    define: { __DEMO__: JSON.stringify(demo) },
    // Keep the marker substitution in Vite's pipeline during local development.
    optimizeDeps: { exclude: ["client-only"] },
    build: {
      assetsInlineLimit: 0,
      outDir: demo ? "dist-demo" : "../src/support_agent/web-react",
      emptyOutDir: true,
      sourcemap: false,
      manifest: true,
      rollupOptions: {
        output: {
          entryFileNames: "assets/app-[hash].js",
          assetFileNames: "assets/[name]-[hash][extname]",
        },
      },
    },
    preview: { proxy: previewProxy },
    server: demo
      ? {}
      : {
          proxy: {
            "/api": "http://127.0.0.1:8000",
            "/widget.js": "http://127.0.0.1:8000",
          },
        },
  };
});
