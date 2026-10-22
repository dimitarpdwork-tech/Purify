import type { Config } from "tailwindcss";

const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        paper: v("paper"),
        panel: v("panel"),
        sunken: v("sunken"),
        rule: v("rule"),
        ink: v("ink"),
        muted: v("muted"),
        faint: v("faint"),
        accent: v("accent"),
        "accent-soft": v("accent-soft"),
        active: v("active"),
        "active-soft": v("active-soft"),
        possible: v("possible"),
        "possible-soft": v("possible-soft"),
        declared: v("declared"),
        "declared-soft": v("declared-soft"),
        danger: v("danger"),
        "danger-soft": v("danger-soft"),
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      fontSize: {
        "2xs": ["10.5px", "14px"],
        xs: ["11.5px", "16px"],
        sm: ["12.5px", "18px"],
        base: ["13.5px", "20px"],
      },
      borderRadius: { DEFAULT: "4px", sm: "3px", md: "5px", lg: "7px" },
    },
  },
  plugins: [],
} satisfies Config;
