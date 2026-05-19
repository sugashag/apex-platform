import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "1rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "#1F4E79",
          foreground: "#FFFFFF",
        },
        accent: {
          DEFAULT: "#2E75B6",
          foreground: "#FFFFFF",
        },
        ai: {
          DEFAULT: "#7C3AED",
          foreground: "#FFFFFF",
          muted: "#F5F3FF",
        },
        success: {
          DEFAULT: "#16A34A",
          foreground: "#FFFFFF",
          muted: "#DCFCE7",
        },
        warning: {
          DEFAULT: "#D97706",
          foreground: "#FFFFFF",
          muted: "#FEF3C7",
        },
        danger: {
          DEFAULT: "#DC2626",
          foreground: "#FFFFFF",
          muted: "#FEE2E2",
        },
        surface: "#FFFFFF",
        muted: {
          DEFAULT: "#F1F5F9",
          foreground: "#6B7280",
        },
        card: {
          DEFAULT: "#FFFFFF",
          foreground: "#111827",
        },
        popover: {
          DEFAULT: "#FFFFFF",
          foreground: "#111827",
        },
        destructive: {
          DEFAULT: "#DC2626",
          foreground: "#FFFFFF",
        },
        secondary: {
          DEFAULT: "#F1F5F9",
          foreground: "#111827",
        },
      },
      borderColor: {
        DEFAULT: "#E2E8F0",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
      },
      borderRadius: {
        lg: "0.5rem",
        md: "0.375rem",
        sm: "0.25rem",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
