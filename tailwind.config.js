module.exports = {
  content: [
    "./**/templates/**/*.html",
    "./core/templates/**/*.html",
    "./templates/*.html",
    "./**/*.py"
  ],
  theme: {
    extend: {
      colors: {
        background: "#0B0F19",
        surface: "#111827",
        muted: "#1F2937",
        border: "#2E3A49",

        primary: {
          500: "#4F46E5",
          600: "#4338CA",
          700: "#3730A3",
          DEFAULT: "#4F46E5",
        },

        accent: {
          DEFAULT: "#14B8A6",
        },

        text: {
          primary: "#FFFFFF",
          secondary: "#D1D5DB",
          muted: "#9CA3AF",
        },

        success: "#22C55E",
        warning: "#F59E0B",
        error: "#EF4444",
      },

      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },

      borderRadius: {
        card: "16px",
        button: "10px",
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}