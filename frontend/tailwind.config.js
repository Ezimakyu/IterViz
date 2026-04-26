/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#0b1020",
        panel: "#11162a",
        ink: "#e6e8ef",
        muted: "#8a93a6",
      },
    },
  },
  plugins: [],
};
