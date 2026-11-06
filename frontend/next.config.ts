import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The container image ships only the files the server needs, which avoids copying all of node_modules.
  output: process.env.NEXT_STANDALONE === "1" ? "standalone" : undefined,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
