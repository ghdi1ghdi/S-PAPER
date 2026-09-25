import {defineConfig,devices} from '@playwright/test';
export default defineConfig({testDir:'./e2e',timeout:90000,workers:1,use:{baseURL:process.env.E2E_URL||'http://localhost:3000',trace:'retain-on-failure',screenshot:'only-on-failure'},projects:[{name:'chromium',use:{...devices['Desktop Chrome']}}],reporter:[['list'],['html',{open:'never'}]]});
