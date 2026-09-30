/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      { protocol: "http", hostname: "localhost", port: "8000", pathname: "/**" },
      { protocol: "https", hostname: "*.up.railway.app", pathname: "/**" },
    ],
  },
  // Proxy /api/* → FastAPI so the browser never needs *.railway.internal
  async rewrites() {
    const backend = (process.env.BACKEND_URL || "").trim().replace(/\/$/, "");
    if (!backend) return [];
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  // react-konva/konva optionally require Node `canvas` (native). Browser UI never needs it.
  // Do NOT npm install `canvas` — it fails on Railway without system libs.
  webpack: (config, { isServer, webpack }) => {
    config.resolve.alias = {
      ...(config.resolve.alias || {}),
      canvas: false,
    };
    config.resolve.fallback = {
      ...(config.resolve.fallback || {}),
      canvas: false,
      encoding: false,
    };
    config.plugins.push(
      new webpack.IgnorePlugin({
        resourceRegExp: /^canvas$/,
      })
    );
    if (isServer) {
      config.externals = [...(config.externals || []), "canvas"];
    }
    return config;
  },
};

module.exports = nextConfig;
