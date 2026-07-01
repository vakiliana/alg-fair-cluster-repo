// render_pdf.js — render the survey to a print/PDF using headless Chromium.
// Serves the repo over a tiny static server (so fetch() of survey/content.html
// and references.json works), opens survey.html, waits for the content +
// KaTeX to finish, then prints to survey.pdf using the page's @media print CSS.
//
// Run by .github/workflows/survey-pdf.yml. Local: `node scripts/render_pdf.js`.

const http = require("http");
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer");

const ROOT = process.cwd();
const PORT = 8137;

const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".json": "application/json",
  ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml",
  ".jpg": "image/jpeg", ".woff2": "font/woff2",
};

function serve() {
  return http.createServer((req, res) => {
    let p = decodeURIComponent(req.url.split("?")[0]);
    if (p === "/") p = "/survey.html";
    const file = path.join(ROOT, p);
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404); res.end("not found"); return;
    }
    res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
}

(async () => {
  const server = serve();
  await new Promise((r) => server.listen(PORT, r));
  const browser = await puppeteer.launch({
    headless: "new",
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });
  const page = await browser.newPage();
  await page.goto(`http://localhost:${PORT}/survey.html`, { waitUntil: "networkidle0", timeout: 60000 });

  // Wait until the article content is injected and KaTeX has rendered.
  await page.waitForFunction(() => {
    const art = document.getElementById("article");
    return art && !art.querySelector(".loading") && document.querySelectorAll(".katex").length > 50;
  }, { timeout: 60000 }).catch(() => {});
  await new Promise((r) => setTimeout(r, 1500));

  await page.pdf({
    path: path.join(ROOT, "survey.pdf"),
    printBackground: true,
    preferCSSPageSize: true,
    format: "A4",
    margin: { top: "0", bottom: "0", left: "0", right: "0" },
  });

  await browser.close();
  server.close();
  console.log("Wrote survey.pdf");
})().catch((e) => { console.error(e); process.exit(1); });
