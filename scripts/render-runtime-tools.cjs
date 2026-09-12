// Render each runtime-tools diagram at its natural size, with 2x resolution.
// Usage: node scripts/render-runtime-tools.cjs /path/to/node_modules
// The module directory must contain mermaid and puppeteer (as installed by mmdc).
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const modules = path.resolve(process.argv[2] || 'node_modules');
  const puppeteer = require(path.join(modules, 'puppeteer'));
  const images = path.resolve(__dirname, '../assets/images');
  const sources = fs.readdirSync(images)
    .filter(name => /^runtime-tools-.*\.mmd$/.test(name)).sort();
  const browser = await puppeteer.launch({headless: true});
  try {
    const page = await browser.newPage();
    await page.setViewport({width: 1800, height: 1000, deviceScaleFactor: 2});
    await page.setContent('<html><head><style>html,body{margin:0;background:white;}#diagram{display:inline-block;padding:12px;}svg{display:block;}</style></head><body><div id="diagram"></div></body></html>');
    await page.addScriptTag({path: path.join(modules, 'mermaid/dist/mermaid.js')});
    for (const name of sources) {
      const source = fs.readFileSync(path.join(images, name), 'utf8');
      const dimensions = await page.evaluate(async source => {
        const container = document.getElementById('diagram');
        container.replaceChildren();
        mermaid.initialize({startOnLoad: false, theme: 'neutral'});
        const result = await mermaid.render('rendered-diagram', source);
        container.innerHTML = result.svg;
        const svg = container.querySelector('svg');
        const box = svg.viewBox.baseVal;
        svg.style.maxWidth = 'none';
        svg.style.width = `${box.width}px`;
        svg.style.height = `${box.height}px`;
        await document.fonts.ready;
        const bounds = container.getBoundingClientRect();
        return {width: Math.ceil(bounds.width), height: Math.ceil(bounds.height)};
      }, source);
      await page.screenshot({
        path: path.join(images, name.replace(/\.mmd$/, '.png')),
        clip: {x: 0, y: 0, ...dimensions},
        captureBeyondViewport: true,
      });
      console.log(`${name}: ${dimensions.width * 2} x ${dimensions.height * 2}`);
    }
  } finally {
    await browser.close();
  }
}

main().catch(error => {console.error(error); process.exitCode = 1;});
