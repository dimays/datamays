/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',      // Django templates
    './**/templates/**/*.html',   // any app templates
    './assets/js/**/*.js',        // any JS files using Tailwind
    './assets/js/**/*.jsx',       // optional, if React/JSX is used
  ],
  theme: {
    extend: {
      // You can extend colors, spacing, fonts, etc.
      colors: {
        brand: '#1e40af',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),       // optional
    require('@tailwindcss/typography'),  // optional
  ],
}
