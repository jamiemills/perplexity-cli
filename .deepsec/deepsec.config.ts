import { defineConfig } from "deepsec/config";

export default defineConfig({
  projects: [
    { id: "perplexity-cli", root: ".." },
    // <deepsec:projects-insert-above>
  ],
});
