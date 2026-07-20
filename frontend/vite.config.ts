import { defineConfig } from 'vitest/config'; import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig({plugins:[react(), tailwindcss()], server:{fs:{allow:[".","../src/bag_doctor/web/dist"]}}, build:{outDir:"../src/bag_doctor/web/dist", emptyOutDir:true}, test:{environment:"jsdom",setupFiles:["./src/test/setup.ts"]}});
