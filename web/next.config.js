/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    unoptimized: true
  },
  // Next blocks cross-origin dev assets by default. localhost is already
  // allowed; 127.0.0.1 is not — ship it so `npm run dev` works at
  // http://127.0.0.1:3000 without a local config tweak.
  allowedDevOrigins: ['127.0.0.1'],
}

module.exports = nextConfig
