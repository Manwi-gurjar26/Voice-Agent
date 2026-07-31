import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Traces and copies only the files actually needed at runtime into
  // .next/standalone (including a minimal server.js) — the Docker image
  // doesn't need node_modules or the dev-only build toolchain at all.
  // See Dockerfile for the two-stage build this enables.
  output: "standalone",
};

export default nextConfig;
