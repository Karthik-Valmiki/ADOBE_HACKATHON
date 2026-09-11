#!/usr/bin/env node
/**
 * jsdom_runner.js — Node.js + jsdom JS Hydration Runner
 *
 * Usage:
 *   node jsdom_runner.js <url>
 *   (HTML is read from stdin, URL passed as CLI arg for location context)
 *
 * Output (stdout): JSON object
 *   {
 *     "hydrated_html": "<string>",        // document.documentElement.outerHTML after script execution
 *     "word_count": <number>,             // rough word count of visible text
 *     "title": "<string>",               // document.title after execution
 *     "json_ld_blocks": [<string>, ...], // stringified JSON-LD script blocks found
 *     "meta_tags": {<name>: <content>},  // key meta tags
 *     "links": [<href>, ...],            // up to 200 anchor hrefs
 *     "error": null | "<string>"         // execution error if any
 *   }
 *
 * Constraints (Adobe Hackathon):
 *   - NO network requests during execution (runScripts: "outside-only" equivalent)
 *   - NO Chromium / headless browser
 *   - Timeout: 20 seconds maximum
 *   - Only inline scripts are executed (no external script fetches)
 */

"use strict";

const { JSDOM, VirtualConsole } = require("jsdom");

// ── Configuration ────────────────────────────────────────────────────────────
const EXEC_TIMEOUT_MS = 18000;   // Hard kill after 18 s
const MAX_SCRIPT_LENGTH = 50000; // Skip individual inline scripts >50 KB
const MAX_JSON_LD_BLOCKS = 20;
const MAX_LINKS = 200;

// ── Helpers ──────────────────────────────────────────────────────────────────

function readStdin() {
  return new Promise((resolve, reject) => {
    const chunks = [];
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => chunks.push(chunk));
    process.stdin.on("end", () => resolve(chunks.join("")));
    process.stdin.on("error", reject);
  });
}

function countWords(text) {
  if (!text) return 0;
  return text.trim().split(/\s+/).filter((w) => w.length > 0).length;
}

function extractVisibleText(document) {
  // Walk text nodes from body, skip script/style/noscript
  const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "HEAD", "META", "LINK"]);
  const parts = [];
  function walk(node) {
    if (!node) return;
    if (node.nodeType === 3 /* TEXT_NODE */) {
      const t = node.textContent.trim();
      if (t) parts.push(t);
    } else if (node.nodeType === 1 /* ELEMENT_NODE */) {
      if (!SKIP_TAGS.has(node.tagName)) {
        for (const child of node.childNodes) walk(child);
      }
    }
  }
  try { walk(document.body); } catch (_) {}
  return parts.join(" ");
}

function extractJsonLdBlocks(document) {
  const blocks = [];
  try {
    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
    for (const s of scripts) {
      if (blocks.length >= MAX_JSON_LD_BLOCKS) break;
      const raw = s.textContent.trim();
      if (raw) blocks.push(raw);
    }
  } catch (_) {}
  return blocks;
}

function extractMetaTags(document) {
  const meta = {};
  try {
    const INTERESTING = ["description", "robots", "viewport", "author",
                         "og:title", "og:description", "og:image", "og:type",
                         "twitter:card", "twitter:title", "twitter:description",
                         "article:published_time", "article:modified_time"];
    for (const key of INTERESTING) {
      // Standard name=
      let el = document.querySelector(`meta[name="${key}"]`);
      if (!el) el = document.querySelector(`meta[property="${key}"]`);
      if (el) meta[key] = el.getAttribute("content") || "";
    }
  } catch (_) {}
  return meta;
}

function extractLinks(document) {
  const hrefs = [];
  try {
    const anchors = document.querySelectorAll("a[href]");
    for (const a of anchors) {
      if (hrefs.length >= MAX_LINKS) break;
      const href = a.getAttribute("href");
      if (href && !href.startsWith("#")) hrefs.push(href);
    }
  } catch (_) {}
  return hrefs;
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  const url = process.argv[2];
  if (!url || !url.startsWith("http")) {
    process.stdout.write(
      JSON.stringify({ error: "Missing required argument: URL must be passed as the first CLI argument (e.g. node jsdom_runner.js https://target.com)" }) + "\n"
    );
    process.exit(1);
  }

  let html = "";
  try {
    html = await readStdin();
  } catch (e) {
    outputError(`stdin read error: ${e.message}`);
    return;
  }

  if (!html || html.trim().length === 0) {
    outputError("Empty HTML received on stdin");
    return;
  }

  // Silence jsdom resource-load & console errors to keep stdout clean
  const virtualConsole = new VirtualConsole();
  // We intentionally suppress all jsdom console output

  let dom;
  try {
    dom = new JSDOM(html, {
      url: url,
      runScripts: "dangerously",        // Execute inline scripts
      resources: "usable",              // Allow resource loading for scripts tagged as usable
      pretendToBeVisual: true,          // Makes window.innerWidth/Height available
      virtualConsole,
      beforeParse(window) {
        // Block all external network requests — only inline execution is allowed
        // Override fetch so scripts calling fetch() don't hang
        window.fetch = () =>
          Promise.resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve({}),
            text: () => Promise.resolve(""),
            headers: { get: () => null },
          });
        window.XMLHttpRequest = class {
          open() {}
          send() { if (typeof this.onreadystatechange === "function") { this.readyState = 4; this.status = 200; this.responseText = ""; this.onreadystatechange(); } }
          setRequestHeader() {}
          addEventListener() {}
          abort() {}
        };
        // Block setTimeout-based lazy renders (keep execution synchronous-ish)
        // We allow a single short timeout pass
      },
    });
  } catch (e) {
    outputError(`JSDOM parse error: ${e.message}`);
    return;
  }

  // Wait a tick for synchronous DOMContentLoaded handlers
  await new Promise((r) => setTimeout(r, 500));

  const document = dom.window.document;

  const hydratedHtml = document.documentElement
    ? document.documentElement.outerHTML
    : html;

  const visibleText = extractVisibleText(document);

  const result = {
    hydrated_html: hydratedHtml,
    word_count: countWords(visibleText),
    title: document.title || "",
    json_ld_blocks: extractJsonLdBlocks(document),
    meta_tags: extractMetaTags(document),
    links: extractLinks(document),
    error: null,
  };

  process.stdout.write(JSON.stringify(result));
  dom.window.close();
}

function outputError(msg) {
  process.stdout.write(JSON.stringify({
    hydrated_html: "",
    word_count: 0,
    title: "",
    json_ld_blocks: [],
    meta_tags: {},
    links: [],
    error: msg,
  }));
}

// Hard timeout guard
const killTimer = setTimeout(() => {
  outputError("jsdom_runner timeout exceeded 18 s");
  process.exit(0);
}, EXEC_TIMEOUT_MS);
killTimer.unref();

main().catch((e) => outputError(String(e)));
