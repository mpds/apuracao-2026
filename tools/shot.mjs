// uso: node tools/shot.mjs <url> <out.png> [largura] [dark]
import { chromium } from "playwright";
const [url, out, w = "390", dark = ""] = process.argv.slice(2);
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: +w, height: 844 }, deviceScaleFactor: 2, colorScheme: dark ? "dark" : "light", isMobile: +w < 600, hasTouch: +w < 600 });
p.on("pageerror", (e) => console.log("PAGEERROR", e.message)); p.on("console", (m) => { if (m.type() === "error") console.log("CONSOLE", m.text()); });
await p.goto(url, { waitUntil: "networkidle" }); await p.waitForTimeout(800);
await p.screenshot({ path: out, fullPage: true }); await b.close(); console.log("ok", out);
