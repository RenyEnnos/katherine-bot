/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                // Custom colors if needed, but we'll stick to standard Tailwind colors for now
                // to keep it clean and "ChatGPT-like"
            },
        },
    },
    plugins: [],
}
