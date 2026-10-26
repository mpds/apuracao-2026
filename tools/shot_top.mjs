import { chromium } from "playwright";
const [url, out, dark = ""] = process.argv.slice(2);
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 390, height: 1100 }, deviceScaleFactor: 2, colorScheme: dark ? "dark" : "light", isMobile: true, hasTouch: true });
p.on("pageerror", (e) => console.log("PAGEERROR", e.message));
await p.goto(url, { waitUntil: "networkidle" }); await p.waitForTimeout(800);
// simula um toque/arraste no gráfico para testar o scrubber
const g = await p.$("#grafico svg"); const bb = await g.boundingBox();
await p.mouse.move(bb.x + bb.width * 0.5, bb.y + bb.height * 0.5); await p.mouse.down(); await p.mouse.move(bb.x + bb.width * 0.6, bb.y + bb.height * 0.5, { steps: 5 }); 
await p.screenshot({ path: out }); await p.mouse.up(); await b.close(); console.log("ok", out);
