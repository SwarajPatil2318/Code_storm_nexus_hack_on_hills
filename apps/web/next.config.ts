import type { NextConfig } from "next";
const config: NextConfig = {
  distDir:
    process.env.NEXUS_UI_WEB === "1"
      ? ".next-ui"
      : process.env.NEXUS_CENTER_WEB === "1"
        ? ".next-center"
        : process.env.NEXUS_TIMING_WEB === "1"
          ? ".next-timing"
          : process.env.NEXUS_RESOURCE_WEB === "1"
            ? ".next-resource"
            : process.env.NEXUS_ASSURANCE_WEB === "1"
              ? ".next-assurance"
              : process.env.NEXUS_DEMO_WEB === "1"
                ? ".next-demo"
                : ".next",
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};
export default config;
