// scrape-fora.mjs
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import puppeteer from 'puppeteer';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// --- Параметри ---
const BASE_URL = 'https://fora.ua/category/molochni-produkty-ta-iaitsia-2656';
const MAX_PAGES = parseInt(process.env.MAX_PAGES || '5', 10);
const OUTPUT_DIR = process.env.OUTPUT_DIR || path.join(__dirname, '..', 'data', 'fora');

const SITE_NAME = 'Fora.ua';
const CATEGORY = 'Молочні продукти та яйця';

function sleep(ms) { return new Promise(res => setTimeout(res, ms)); }

function extractPrice(text) {
  if (!text) return null;
  let cleaned = text.replace(/[₴грнUAH]/gi, '').replace(',', '.').replace(/\s+/g, '').trim();
  const m = cleaned.match(/(\d+(\.\d+)?)/);
  if (!m) return null;
  const val = parseFloat(m[1]);
  if (isNaN(val) || val < 0.5 || val > 10000) return null;
  return val;
}

async function scrapePage(page, url) {
  await page.goto(url, { waitUntil: 'networkidle2', timeout: 120000 });

  // Типові обгортки для карток товарів (ставимо кілька спроб)
  const cardSelectors = [
    "div[class*='product-card']",
    ".product-item",
    "[data-testid*='product']",
    ".js-product-item",
    "li[class*='product']",
    "article[class*='product']"
  ];

  // Дочекаємось, поки відмальуються хоч якісь карти
  let found = false;
  for (const sel of cardSelectors) {
    try {
      await page.waitForSelector(sel, { timeout: 8000 });
      found = true;
      break;
    } catch (_) {}
  }

  if (!found) {
    // якщо не дочекались конкретних селекторів — дамо сторінці шанс
    await sleep(2000);
  }

  // Парсимо все в браузері — збираємо максимум із різних селекторів
  const items = await page.evaluate((cardSelectors) => {
    function getText(el) { return (el && el.textContent || '').trim(); }

    function selOne(el, list) {
      for (const s of list) {
        const e = el.querySelector(s);
        if (e) return e;
      }
      return null;
    }

    const cardList = [];
    const root = document;

    // Зберемо всі можливі картки
    const sets = cardSelectors.map(sel => Array.from(root.querySelectorAll(sel)));
    const cards = Array.from(new Set(sets.flat())); // унікалізуємо

    for (const card of cards) {
      // title candidates
      const titleEl = selOne(card, [
        "div[class*='title']",
        "div[class*='name']",
        ".product-title",
        "h3 a", "h3",
        "a[title]", "a[class*='title']",
        "[data-testid*='title']"
      ]);

      // link candidates
      const linkEl = selOne(card, [
        "a[href*='/product/']",
        "a[href]",
        "a"
      ]);

      // price candidates
      const priceEl = selOne(card, [
        "div[class*='price']", "span[class*='price']",
        ".price", "[class*='cost']",
        "[class*='Price']"
      ]);

      // image candidates
      const imgEl = selOne(card, [
        "img[class*='product']",
        ".product-image img",
        "img"
      ]);

      const title = getText(titleEl);
      const href = linkEl && linkEl.getAttribute('href') || '';
      const url = href ? new URL(href, location.origin).toString() : null;
      const priceText = getText(priceEl);
      const image = imgEl && (imgEl.getAttribute('src') || imgEl.getAttribute('data-src')) || null;

      if (url) {
        cardList.push({
          url,
          product_name: title || null,
          price_text: priceText || null,
          image_url: image && (image.startsWith('http') ? image : new URL(image, location.origin).toString())
        });
      }
    }
    return cardList;
  }, cardSelectors);

  return items;
}

(async () => {
  const browser = await puppeteer.launch({
    headless: true, // headless by default on Actions
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  const page = await browser.newPage();
  page.setDefaultTimeout(60000);

  const sessionId = `fora_${new Date().toISOString().replace(/[:-]/g, '').split('.')[0]}`;
  const scrapedAt = new Date().toISOString();
  const results = [];
  const fails = [];

  try {
    for (let p = 1; p <= MAX_PAGES; p++) {
      const url = p === 1 ? BASE_URL : `${BASE_URL}?page=${p}`;
      console.log(`[Fora] Page ${p}/${MAX_PAGES}: ${url}`);

      try {
        const items = await scrapePage(page, url);
        // нормалізація
        for (const it of items) {
          results.push({
            site_name: 'Fora.ua',
            category: 'Молочні продукти та яйця',
            product_name: it.product_name,
            price: extractPrice(it.price_text),
            currency: '₴',
            image_url: it.image_url || null,
            url: it.url,
            scraped_at: scrapedAt,
            session_id: sessionId
          });
        }
      } catch (err) {
        console.error(`[Fora] Error page ${p}:`, err?.message || err);
        fails.push({ page: p, url, error: String(err?.message || err) });
      }

      await sleep(500 + Math.random() * 800);
    }
  } finally {
    await browser.close();
  }

  // Пишемо JSON
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  const outPath = path.join(OUTPUT_DIR, `fora_products_${sessionId}.json`);
  fs.writeFileSync(outPath, JSON.stringify({
    site: SITE_NAME,
    category: CATEGORY,
    session_id: sessionId,
    scraped_at: scrapedAt,
    max_pages: MAX_PAGES,
    items: results,
    fails
  }, null, 2), 'utf-8');

  console.log(`[Fora] Saved: ${outPath}`);
  console.log(`[Fora] Items: ${results.length}, Fails: ${fails.length}`);
})().catch(e => {
  console.error('[Fora] Fatal error:', e);
  process.exit(1);
});
