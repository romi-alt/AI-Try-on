/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  images: {
    // Media comes from MinIO locally and R2 in production; allow any https host
    // plus the local MinIO port. Tighten this once the public R2 domain is known.
    remotePatterns: [
      { protocol: "http", hostname: "localhost" },
      { protocol: "http", hostname: "minio" },
      { protocol: "https", hostname: "**" },
    ],
  },
};

export default nextConfig;
