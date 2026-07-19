import { defineConfig } from "vite";
import { resolve } from "path";

export default defineConfig({

  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/resources": "http://localhost:8000",
      "/debug": "http://localhost:8000",
      "/view": "http://localhost:8000"
    }
  },

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
          resolve(__dirname, "meshbank.html"),

        animbank:
          resolve(__dirname, "animbank.html"),

        social_debug:
          resolve(__dirname, "social_debug.html"),

        character_creator:
          resolve(__dirname, "character_creator.html")
      }
    }
  }
});
