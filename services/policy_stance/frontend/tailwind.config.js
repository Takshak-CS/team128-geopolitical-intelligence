export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#07131f',
        storm: '#102335',
        ember: '#ff8c42',
        mint: '#62d2a2',
        steel: '#8aa5bf',
      },
      boxShadow: {
        panel: '0 30px 70px rgba(5, 17, 28, 0.28)',
      },
      backgroundImage: {
        grid: 'linear-gradient(rgba(138,165,191,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(138,165,191,0.08) 1px, transparent 1px)',
      },
      fontFamily: {
        display: ['Space Grotesk', 'sans-serif'],
        body: ['IBM Plex Sans', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
