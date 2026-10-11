/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3000',
    NEXT_PUBLIC_GOOGLE_CLIENT_ID: process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || '',
  },
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: '**' },
      { protocol: 'http', hostname: 'localhost' },
    ],
  },
  async rewrites() {
    // In Docker, use the backend service name; externally use env var
    const apiUrl = process.env.DOCKER_ENV === '1' ? 'http://app:3000' : (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3000');
    return [
      {
        source: '/api/tts/preview',
        destination: `${apiUrl}/api/tts/preview`,
      },
    ];
  },
  async redirects() {
    return [
      { source: '/dashboard/live', destination: '/dashboard/calls', permanent: true },
      { source: '/dashboard/agents/builder', destination: '/dashboard/agents/new', permanent: true },
    ];
  },
};

module.exports = nextConfig;
