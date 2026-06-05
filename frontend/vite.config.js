import { defineConfig } from "vite";
import { resolve } from "path";

export default defineConfig({

  build: {

    rollupOptions: {

      input: {

        main:
          resolve(__dirname, "index.html"),

        editor:
          resolve(__dirname, "editor.html"),

        definitions:
          resolve(__dirname, "definitions.html"),

        floorplan:
          resolve(__dirname, "floorplan.html"),

        meshbank:
          resolve(__dirname, "meshbank.html")
      }
    }
  }
});