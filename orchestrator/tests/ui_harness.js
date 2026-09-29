// Runs the briefing UI's own script (static/index.html) against a minimal DOM
// and prints what one agent's panel rendered, so Python tests can check the
// page itself rather than only the API behind it.
//
//   node tests/ui_harness.js <index.html> <agent label>  < response.json
//
// Prints {"views": [data-view ids in document order], "headings": [...],
// "headlines": [...], "text": "..."} for the panel whose title is the label.

const fs = require("fs");
const vm = require("vm");

class FakeNode {
  constructor(tag = "#text", text = "") {
    this.tag = tag;
    this.children = [];
    this.attrs = {};
    this.className = "";
    this.style = {};
    this.value = "";
    this.data = text;
    this.classList = {
      add: (c) => { this.className = `${this.className} ${c}`.trim(); },
      remove: (c) => { this.className = this.className.split(" ").filter((x) => x !== c).join(" "); },
    };
  }
  append(...nodes) { for (const n of nodes) this.children.push(n instanceof FakeNode ? n : new FakeNode("#text", String(n))); }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key]; }
  addEventListener() {}
  get textContent() { return this.tag === "#text" ? this.data : this.children.map((c) => c.textContent).join(""); }
  set textContent(text) { this.children = [new FakeNode("#text", String(text))]; }
}

const byId = new Map();
const document = {
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, new FakeNode("div")); return byId.get(id); },
  createElement: (tag) => new FakeNode(tag),
  createElementNS: (_ns, tag) => new FakeNode(tag),
  createTextNode: (text) => new FakeNode("#text", String(text)),
  querySelectorAll: () => [],
};

const [page, label] = process.argv.slice(2);
const html = fs.readFileSync(page, "utf8");
const script = html.slice(html.indexOf("<script>") + "<script>".length, html.lastIndexOf("</script>"));
const context = vm.createContext({
  document, window: {}, Node: FakeNode, URL, console, performance,
  fetch: () => Promise.reject(new Error("no network in tests")),
  setInterval: () => 0,
});
vm.runInContext(`${script}\nglobalThis.__render = render;`, context);
context.__render(JSON.parse(fs.readFileSync(0, "utf8")));

function* walk(node) { yield node; for (const child of node.children) yield* walk(child); }
const panel = [...walk(document.getElementById("agents"))].find((n) =>
  n.tag === "article" && n.className.includes("panel") && [...walk(n)].some((h) => h.tag === "h4" && h.textContent === label));
if (!panel) { console.log(JSON.stringify({ error: `no panel titled ${label}` })); process.exit(0); }
const nodes = [...walk(panel)];
console.log(JSON.stringify({
  views: nodes.filter((n) => n.attrs["data-view"]).map((n) => n.attrs["data-view"]),
  headings: nodes.filter((n) => n.tag === "h5").map((n) => n.textContent),
  headlines: nodes.filter((n) => n.tag === "p" && n.className === "what").map((n) => n.textContent),
  text: panel.textContent,
}));
