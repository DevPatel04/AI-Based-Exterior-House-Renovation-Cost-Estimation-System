/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Brand scale (pine green) — primary actions, focus, active states
        brand: {
          50: "#eef7f4",
          100: "#d6ece5",
          200: "#aed8cb",
          300: "#7cbba9",
          400: "#4f9c87",
          500: "#34816d",
          600: "#276a59",
          700: "#205649",
          800: "#1c463c",
          900: "#183a33",
        },
        // Accent scale (clay) — highlights, handles, secondary emphasis
        accent: {
          50: "#fdf4ee",
          100: "#fae3d3",
          200: "#f4c3a4",
          400: "#e2834f",
          500: "#d06a33",
          600: "#b85726",
          700: "#98441e",
        },
        // Legacy tokens kept for compatibility
        ink: "#0f172a",
        mist: "#e2e8f0",
        clay: "#b85726",
        pine: "#276a59",
        sand: "#f8fafc",
      },
      fontFamily: {
        display: ["var(--font-display)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "system-ui", "Segoe UI", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)",
        pop: "0 10px 30px -10px rgb(15 23 42 / 0.25), 0 4px 10px -6px rgb(15 23 42 / 0.12)",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in 150ms ease-out",
        "slide-up": "slide-up 180ms ease-out",
      },
    },
  },
  plugins: [],
};
