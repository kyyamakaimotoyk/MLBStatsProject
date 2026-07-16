import type { NextConfig } from "next";

// Static export for S3 + CloudFront (the hoopmodel deployment model).
// trailingSlash gives every route a directory index.html that CloudFront
// can serve with a url-rewrite function; dynamic data loads client-side.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
