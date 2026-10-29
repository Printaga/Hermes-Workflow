/**
 * Hermes Workflows — desktop plugin (runtime-loaded: plain ESM, no build).
 *
 * The desktop host reads this file as raw text, rewrites the two allowed specifiers to its live
 * shim blobs, imports it, validates the default export as a HermesPlugin, and calls
 * `register(ctx)` (apps/desktop/src/contrib/runtime-loader.ts). Only `@hermes/plugin-sdk` and
 * `react*` resolve here, and this host exposes no React hooks, so the page shell is one element
 * and the canvas mounts from a stable ref callback.
 *
 * Contributions:
 *   routes       full page at /workflows (RouteContribution: data.path + title + render)
 *   sidebar.nav  row { codicon: 'project', label: 'Workflows', path: '/workflows' }
 *
 * The canvas core is the same vanilla DOM/SVG designer the dashboard tab uses. The backend is
 * this package's own router (dashboard/plugin_api.py) reached ONLY through `ctx.rest`, which the
 * host scopes to /api/plugins/visual-workflow and authenticates itself — no fetch, no tokens:
 *   GET  /designs                     saved design names
 *   GET  /designs/{name}              one graph
 *   POST /designs/{name}              validate + save a graph
 *   POST /designs/{name}/validate     validate a saved design or a draft {"graph": ...}
 *   POST /designs/{name}/run          run now, until done or paused
 *   POST /runs/{run_id}/respond       answer an approval gate / a pending agent step
 */
import { jsx } from "react/jsx-runtime";

const SVG_NS = "http://www.w3.org/2000/svg";
const KINDS = ["trigger", "agent", "condition", "approval", "output"];
const MODES = ["manual", "schedule", "webhook"];
const NODE_W = 168;
const NODE_H = 56;
const PORT_R = 5;

// ---- edge geometry (identical in desktop/plugin.js, dashboard/dist/index.js and
// widgets/designer.html: no build step, so the block is copied rather than imported).
// Every node has an OUTPUT port on its right edge and — except a trigger, which can have
// no parents — an INPUT port on its left edge. An edge is drawn from the parent's output
// port to the child's input port, so the curve reads as a direction.
function outPort(n) {
  return { x: n.x + NODE_W, y: n.y + NODE_H / 2 };
}

function inPort(n) {
  return { x: n.x, y: n.y + NODE_H / 2 };
}

function edgeKey(from, to) {
  return from + ">" + to;
}

function edgePath(parent, child) {
  const p = outPort(parent);
  const q = inPort(child);
  const bend = Math.max(30, Math.abs(q.x - p.x) / 2);
  return "M" + p.x + "," + p.y +
    "C" + (p.x + bend) + "," + p.y + " " + (q.x - bend) + "," + q.y + " " + q.x + "," + q.y;
}

// JSON (not a JS literal) so the base graph stays the same shape the tools accept.
const BLANK_JSON =
  '{"name":"untitled","nodes":[{"id":"trigger1","type":"trigger","trigger_mode":"manual","after":[]}]}';
const BLANK = JSON.parse(BLANK_JSON);

// Self-contained palette: the desktop shell's own tokens don't have to match the web dashboard's,
// and every value below resolves on its own (fallbacks included) so the canvas cannot compute
// black. Shared by the node fills and the SVG paint attributes (see svgEl).
const CSS = [
  ".vw-shell{--vw-ink:var(--midground,#ffe6cb);--vw-dim:color-mix(in srgb,var(--midground,#ffe6cb) 72%,transparent);--vw-surface:color-mix(in srgb,var(--midground,#ffe6cb) 5%,var(--background,#041c1c));--vw-line:color-mix(in srgb,var(--midground,#ffe6cb) 16%,transparent);--vw-node:color-mix(in srgb,var(--midground,#ffe6cb) 7%,var(--background,#041c1c));--vw-accent:var(--series-output-token,#34d399);--vw-danger:#fb2c36;display:flex;height:100%;min-height:420px;font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--vw-ink);text-align:left}",
  ".vw-rail{flex:0 0 190px;padding:10px 12px;border-right:1px solid var(--vw-line);background:var(--vw-surface);overflow:auto}",
  ".vw-rail-title{margin:0 0 6px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--vw-dim)}",
  ".vw-list{display:flex;flex-direction:column;gap:4px;margin:0 0 10px}",
  ".vw-stage{flex:1 1 auto;min-width:0;display:flex}",
  ".vw-app{display:flex;flex-direction:column;flex:1 1 auto;min-height:0;padding:8px 10px}",
  ".vw-bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:0 0 8px;border-bottom:1px solid var(--vw-line)}",
  ".vw-bar .vw-grow{flex:1 1 160px;min-width:110px}",
  ".vw-main{display:flex;flex:1 1 auto;min-height:0}",
  ".vw-palette{flex:0 0 130px;padding:8px 10px 8px 0;border-right:1px solid var(--vw-line)}",
  ".vw-palette .vw-pill{display:block;width:100%;margin:0 0 6px;text-align:left}",
  ".vw-wrap{flex:1 1 auto;min-width:0;overflow:auto;padding:8px}",
  ".vw-inspector{flex:0 0 250px;padding:8px 0 8px 10px;border-left:1px solid var(--vw-line);overflow:auto}",
  ".vw-errors,.vw-run{margin:0;padding:6px 0;border-top:1px solid var(--vw-line);white-space:pre-wrap;color:var(--vw-dim);max-height:150px;overflow:auto}",
  ".vw-run h4{margin:2px 0 4px;font-size:12px;color:var(--vw-ink)}",
  ".vw-run pre{margin:2px 0 6px;white-space:pre-wrap;max-height:96px;overflow:auto}",
  ".vw-pill,select,input[type=text],textarea{font:inherit;color:inherit;background:var(--vw-node);border:1px solid var(--vw-line);border-radius:6px;padding:3px 7px}",
  ".vw-pill{cursor:pointer}",
  ".vw-pill:hover{border-color:var(--vw-accent)}",
  ".vw-pill[aria-pressed=true]{border-color:var(--vw-accent)}",
  "input[type=text],textarea,select{width:100%;box-sizing:border-box}",
  "textarea{resize:vertical}",
  ".vw-muted{color:var(--vw-dim);margin:2px 0}",
  ".vw-label{color:var(--vw-dim);font-size:11px;margin:8px 0 2px}",
  ".vw-hint,.vw-error{color:var(--vw-dim);font-size:11px;margin:2px 0}",
  ".vw-error{color:var(--vw-danger)}",
  ".vw-canvas{display:block}",
  ".vw-canvas g.vw-node{cursor:grab}",
  ".vw-canvas g.vw-node:active{cursor:grabbing}",
  ".vw-port{fill:var(--vw-surface);stroke:var(--vw-line);stroke-width:1.5;cursor:crosshair}",
  ".vw-port:hover{fill:var(--vw-accent);stroke:var(--vw-accent)}",
  ".vw-edge{fill:none;stroke:var(--vw-line);stroke-width:1.6}",
  ".vw-edge-on{stroke:var(--vw-accent);stroke-width:2.4}",
  ".vw-edge-hit{fill:none;stroke:transparent;stroke-width:12;cursor:pointer}",
  ".vw-ghost{fill:none;stroke:var(--vw-accent);stroke-width:1.6;stroke-dasharray:4 3}",
].join("\n");

const TEMPLATE =
  '<div class="vw-rail">' +
  '  <p class="vw-rail-title">Saved workflows</p>' +
  '  <div class="vw-list" data-vw="designs"></div>' +
  '  <button class="vw-pill" type="button" data-vw="new">New design</button>' +
  '  <p class="vw-error" data-vw="rail-error"></p>' +
  "</div>" +
  '<div class="vw-stage">' +
  '  <div class="vw-app">' +
  '    <div class="vw-bar">' +
  '      <input class="vw-grow" data-vw="name" type="text" value="untitled" aria-label="design name">' +
  '      <button class="vw-pill" type="button" data-vw="validate">Validate</button>' +
  '      <button class="vw-pill" type="button" data-vw="save">Save</button>' +
  '      <button class="vw-pill" type="button" data-vw="run-now">Run</button>' +
  '      <button class="vw-pill" type="button" data-vw="connect">Connect</button>' +
  '      <button class="vw-pill" type="button" data-vw="delete">Delete</button>' +
  '      <span class="vw-muted" data-vw="status"></span>' +
  "    </div>" +
  '    <div class="vw-main">' +
  '      <div class="vw-palette">' +
  '        <button class="vw-pill" type="button" draggable="true" data-kind="trigger">Trigger</button>' +
  '        <button class="vw-pill" type="button" draggable="true" data-kind="agent">Agent</button>' +
  '        <button class="vw-pill" type="button" draggable="true" data-kind="condition">Condition</button>' +
  '        <button class="vw-pill" type="button" draggable="true" data-kind="approval">Approval</button>' +
  '        <button class="vw-pill" type="button" draggable="true" data-kind="output">Output</button>' +
  '        <p class="vw-hint">Drag from a node&rsquo;s right port to another node&rsquo;s left port. Click an edge, then Delete, to cut it.</p>' +
  "      </div>" +
  '      <div class="vw-wrap" data-vw="wrap">' +
  '        <svg class="vw-canvas" data-vw="canvas" width="900" height="560" role="img" aria-label="workflow canvas"></svg>' +
  "      </div>" +
  '      <div class="vw-inspector" data-vw="inspector"></div>' +
  "    </div>" +
  '    <div class="vw-run" data-vw="run"></div>' +
  '    <pre class="vw-errors" data-vw="errors"></pre>' +
  "  </div>" +
  "</div>";

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

/** Rest errors carry the HTTP status in their message; surface the server's `detail` text. */
function explain(err) {
  const text = err && err.message ? err.message : String(err);
  const i = text.indexOf(": ");
  if (i > 0 && /^\d{3}$/.test(text.slice(0, i))) {
    const body = text.slice(i + 2);
    try {
      const parsed = JSON.parse(body);
      if (parsed && parsed.detail) {
        return typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
      }
    } catch (ignored) {
      /* not JSON: show the body as-is */
    }
    return body;
  }
  return text;
}

// SVG presentation attributes are parsed as attribute values, where var() is not valid —
// setAttribute("fill", "var(--vw-node)") computes black. Paint values go through a style
// declaration instead; every other attribute stays a plain attribute.
const PAINT_ATTRS = { fill: 1, stroke: 1, "stop-color": 1 };

function svgEl(name, attrs) {
  const el = document.createElementNS(SVG_NS, name);
  Object.keys(attrs || {}).forEach((key) => {
    const value = attrs[key];
    if (PAINT_ATTRS[key] && String(value).indexOf("var(") >= 0) {
      el.style.setProperty(key, value);
    } else {
      el.setAttribute(key, value);
    }
  });
  return el;
}

/**
 * Mount the designer (rail · palette · SVG graph · inspector · run box) into *host*.
 *
 * Plain DOM/SVG end to end: React only supplies the mount point, so the graph never lives in
 * the host's render tree and dragging does not re-render the app.
 */
function createDesigner(host, call) {
  host.className = "vw-shell";
  host.textContent = "";
  const style = document.createElement("style");
  style.textContent = CSS;
  host.appendChild(style);
  host.insertAdjacentHTML("beforeend", TEMPLATE);

  const q = (sel) => host.querySelector(sel);
  const el = {
    designs: q('[data-vw="designs"]'),
    railError: q('[data-vw="rail-error"]'),
    name: q('[data-vw="name"]'),
    canvas: q('[data-vw="canvas"]'),
    wrap: q('[data-vw="wrap"]'),
    inspector: q('[data-vw="inspector"]'),
    errors: q('[data-vw="errors"]'),
    status: q('[data-vw="status"]'),
    run: q('[data-vw="run"]'),
  };

  let graph = clone(BLANK);
  let designs = [];
  let active = "";
  let selected = null;
  let selectedEdge = null;
  let linkQueue = [];
  let linkArm = null;   // source node id after a click on an output port
  let dragLink = null;  // live drag from an output port: {from, x1, y1, x2, y2}
  let profiles = [];    // host profiles ("bots") offered to agent nodes
  let lastRun = null;

  function nodeById(id) {
    const hits = graph.nodes.filter((n) => n.id === id);
    return hits[0] || null;
  }

  function layout() {
    graph.nodes.forEach((n, i) => {
      if (typeof n.x !== "number" || typeof n.y !== "number") {
        n.x = 30 + (i % 4) * 196;
        n.y = 40 + Math.floor(i / 4) * 128;
      }
    });
  }

  function preview(n) {
    let text =
      n.type === "agent" ? n.prompt || "" :
      n.type === "condition" ? n.expression || "" :
      n.type === "approval" ? n.question || "" :
      n.type === "trigger" ? (n.trigger_mode || "") + (n.schedule ? " " + n.schedule : "") :
      (n.after || []).join(", ");
    text = String(text).replace(/\s+/g, " ").trim();
    return text.length > 26 ? text.slice(0, 25) + "\u2026" : text;
  }

  function draw() {
    const svg = el.canvas;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const byId = {};
    graph.nodes.forEach((n) => {
      byId[n.id] = n;
    });

    graph.nodes.forEach((n) => {
      (n.after || []).forEach((dep) => {
        const parent = byId[dep];
        if (!parent) return;
        const d = edgePath(parent, n);
        const on = selectedEdge === edgeKey(parent.id, n.id);
        const path = svgEl("path", { d: d, class: on ? "vw-edge vw-edge-on" : "vw-edge" });
        // A 1.6px stroke is nearly impossible to hit; the transparent twin is the target.
        const hit = svgEl("path", { d: d, class: "vw-edge-hit", "data-edge": edgeKey(parent.id, n.id) });
        const cut = (ev) => {
          ev.stopPropagation();
          selectedEdge = edgeKey(parent.id, n.id);
          selected = null;
          buildInspector();
          draw();
        };
        path.addEventListener("click", cut);
        hit.addEventListener("click", cut);
        hit.addEventListener("dblclick", (ev) => {
          ev.stopPropagation();
          cutEdge(parent.id, n.id);
        });
        svg.appendChild(path);
        svg.appendChild(hit);
      });
    });

    if (dragLink) {
      svg.appendChild(svgEl("path", {
        d: "M" + dragLink.x1 + "," + dragLink.y1 + "L" + dragLink.x2 + "," + dragLink.y2,
        class: "vw-ghost",
      }));
    }

    graph.nodes.forEach((n) => {
      const isSelected = n.id === selected;
      const queued = linkQueue.indexOf(n.id) >= 0;
      const g = svgEl("g", {
        transform: "translate(" + n.x + "," + n.y + ")",
        class: "vw-node",
        "data-id": n.id,
      });
      g.appendChild(svgEl("rect", {
        width: NODE_W, height: NODE_H, rx: 6,
        fill: "var(--vw-node)",
        stroke: isSelected || queued ? "var(--vw-accent)" : "var(--vw-line)",
        "stroke-width": isSelected ? 2 : 1,
      }));
      const kind = svgEl("text", { x: 10, y: 16, "font-size": 9, fill: "var(--vw-dim)" });
      kind.textContent = String(n.type).toUpperCase();
      const id = svgEl("text", { x: 10, y: 32, "font-size": 12, fill: "var(--vw-ink)" });
      id.textContent = n.id;
      const sub = svgEl("text", { x: 10, y: 46, "font-size": 10, fill: "var(--vw-dim)" });
      sub.textContent = preview(n);
      g.appendChild(kind);
      g.appendChild(id);
      g.appendChild(sub);

      const out = svgEl("circle", {
        cx: NODE_W, cy: NODE_H / 2, r: PORT_R, class: "vw-port",
        "data-port": "out", "data-id": n.id,
      });
      out.addEventListener("mousedown", (ev) => {
        // The port owns the gesture; without this the node drag starts instead.
        ev.stopPropagation();
        ev.preventDefault();
        beginLink(n, ev);
      });
      g.appendChild(out);

      if (n.type !== "trigger") {
        const inp = svgEl("circle", {
          cx: 0, cy: NODE_H / 2, r: PORT_R, class: "vw-port",
          "data-port": "in", "data-id": n.id,
        });
        inp.addEventListener("mousedown", (ev) => {
          ev.stopPropagation();
          ev.preventDefault();
          if (linkArm) finishLink(linkArm, n.id);
          else note("Drag from the right port of the parent node to here.");
        });
        g.appendChild(inp);
      }

      wireNode(g, n);
      svg.appendChild(g);
    });
  }

  function svgPoint(ev) {
    const svg = el.canvas;
    const pt = svg.createSVGPoint();
    pt.x = ev.clientX;
    pt.y = ev.clientY;
    const matrix = svg.getScreenCTM();
    return matrix ? pt.matrixTransform(matrix.inverse()) : { x: ev.clientX, y: ev.clientY };
  }

  function wireNode(g, n) {
    g.addEventListener("mousedown", (ev) => {
      if (ev.button !== 0) return;
      // A port handler already claimed this press (stopPropagation also covers it, but a port
      // inside a child <g> must never drag the node).
      if (ev.target && ev.target.getAttribute && ev.target.getAttribute("data-port")) return;
      ev.preventDefault();
      const start = svgPoint(ev);
      const offset = { x: start.x - n.x, y: start.y - n.y };
      let moved = false;
      function onMove(moveEv) {
        const p = svgPoint(moveEv);
        if (Math.abs(p.x - start.x) > 3 || Math.abs(p.y - start.y) > 3) moved = true;
        n.x = Math.max(0, Math.round(p.x - offset.x));
        n.y = Math.max(0, Math.round(p.y - offset.y));
        draw();
      }
      function onUp() {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        if (!moved) pick(n.id);
      }
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }

  function pick(id) {
    selected = id;
    selectedEdge = null;
    // The queue is "the two most recently clicked nodes", parent first. Clicking a node
    // again must not drop it (that would make click-click-Connect impossible).
    linkQueue = linkQueue.filter((x) => x !== id).concat([id]).slice(-2);
    buildInspector();
    draw();
  }

  /** The node under a canvas point, by geometry (DOM hit-testing would trip over the
   *  edge hit-areas and the drag ghost stacked above the node). */
  function nodeIdAtPoint(p) {
    const PAD = 6;
    for (let i = graph.nodes.length - 1; i >= 0; i -= 1) {
      const n = graph.nodes[i];
      if (p.x >= n.x - PAD && p.x <= n.x + NODE_W + PAD &&
          p.y >= n.y - PAD && p.y <= n.y + NODE_H + PAD) return n.id;
    }
    return null;
  }

  /** Would making *to* depend on *from* close a loop? Walk up from *from*. */
  function createsCycle(from, to) {
    const seen = {};
    let stack = [from];
    while (stack.length) {
      const id = stack.pop();
      if (id === to) return true;
      if (seen[id]) continue;
      seen[id] = 1;
      const n = nodeById(id);
      if (n) stack = stack.concat(n.after || []);
    }
    return false;
  }

  /** Drag started on *n*'s output port: follow the pointer, connect on release. */
  function beginLink(n, ev) {
    const start = svgPoint(ev);
    const origin = outPort(n);
    let moved = false;
    linkArm = null;
    dragLink = { from: n.id, x1: origin.x, y1: origin.y, x2: start.x, y2: start.y };
    draw();
    function onMove(moveEv) {
      const p = svgPoint(moveEv);
      if (Math.abs(p.x - start.x) > 3 || Math.abs(p.y - start.y) > 3) moved = true;
      dragLink.x2 = p.x;
      dragLink.y2 = p.y;
      draw();
    }
    function onUp(upEv) {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      const from = dragLink.from;
      dragLink = null;
      if (moved) {
        const targetId = nodeIdAtPoint(svgPoint(upEv));
        if (targetId && targetId !== from) finishLink(from, targetId);
        else {
          note("");
          draw();
        }
        return;
      }
      // A click (no drag) arms the port, so the next input-port click completes it.
      linkArm = from;
      note("Now click the input port of the node that should run after " + from + ".");
      draw();
    }
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  /** Add the *from* -> *to* edge, refusing the three ways it could be wrong. */
  function finishLink(from, to) {
    linkArm = null;
    const source = nodeById(from);
    const target = nodeById(to);
    if (!source || !target) return;
    if (target.type === "trigger") {
      note("a trigger cannot have parents");
    } else if (from === to) {
      note("a node cannot depend on itself");
    } else if (createsCycle(from, to)) {
      note("that edge would close a loop");
    } else {
      target.after = target.after || [];
      if (target.after.indexOf(from) >= 0) note(from + " already feeds " + to);
      else {
        target.after.push(from);
        note(from + " \u2192 " + to);
      }
    }
    selectedEdge = null;
    draw();
    buildInspector();
  }

  function cutEdge(from, to) {
    const target = nodeById(to);
    if (target) {
      target.after = (target.after || []).filter((dep) => dep !== from);
    }
    selectedEdge = null;
    note("cut " + from + " \u2192 " + to);
    draw();
    buildInspector();
  }

  function connect() {
    if (linkQueue.length < 2) {
      note("Drag from a node's right port to another node's left port.");
      return;
    }
    finishLink(linkQueue[0], linkQueue[1]);
  }

  function removeSelected() {
    if (selectedEdge) {
      const parts = selectedEdge.split(">");
      cutEdge(parts[0], parts[1]);
      return;
    }
    if (!selected) {
      note("Select a node or an edge first.");
      return;
    }
    const removed = selected;
    graph.nodes = graph.nodes.filter((n) => n.id !== removed);
    graph.nodes.forEach((n) => {
      n.after = (n.after || []).filter((dep) => dep !== removed);
    });
    selected = null;
    selectedEdge = null;
    linkQueue = [];
    linkArm = null;
    buildInspector();
    draw();
    note("removed " + removed);
  }

  function field(labelText, control) {
    const wrap = document.createElement("div");
    const label = document.createElement("div");
    label.className = "vw-label";
    label.textContent = labelText;
    wrap.appendChild(label);
    wrap.appendChild(control);
    return wrap;
  }

  function textInput(value, onInput, placeholder) {
    const input = document.createElement("input");
    input.type = "text";
    input.value = value || "";
    if (placeholder) input.placeholder = placeholder;
    input.addEventListener("input", () => {
      onInput(input.value);
    });
    return input;
  }

  function textArea(value, onInput, rows) {
    const area = document.createElement("textarea");
    area.rows = rows || 4;
    area.value = value || "";
    area.addEventListener("input", () => {
      onInput(area.value);
    });
    return area;
  }

  function profileByName(name) {
    if (!name) return null;
    const hits = profiles.filter((p) => p.name === name);
    return hits[0] || null;
  }

  /** Host profiles as a <select>; degrades to the placeholder when none are listed. */
  function profileSelect(current) {
    const select = document.createElement("select");
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = profiles.length ? "\u2014 host default \u2014" : "\u2014 no profiles listed \u2014";
    select.appendChild(blank);
    let known = false;
    profiles.forEach((p) => {
      const option = document.createElement("option");
      option.value = p.name;
      option.textContent = p.label && p.label !== p.name ? p.label + " (" + p.name + ")" : p.name;
      if (p.name === current.profile) {
        option.selected = true;
        known = true;
      }
      select.appendChild(option);
    });
    if (current.profile && !known) {
      // A saved design can name a profile that was renamed or removed: keep the value visible
      // instead of silently resetting it.
      const stale = document.createElement("option");
      stale.value = current.profile;
      stale.textContent = current.profile + " (not found)";
      stale.selected = true;
      select.appendChild(stale);
    }
    select.addEventListener("change", () => {
      if (select.value) current.profile = select.value;
      else delete current.profile;
      buildInspector();
      draw();
    });
    return select;
  }

  function buildInspector() {
    const box = el.inspector;
    box.textContent = "";
    const current = selected ? nodeById(selected) : null;
    if (!current) {
      const empty = document.createElement("p");
      empty.className = "vw-muted";
      empty.textContent = "Select a node to edit it.";
      box.appendChild(empty);
      return;
    }
    const head = document.createElement("p");
    head.className = "vw-muted";
    head.textContent = current.id + " \u00b7 " + current.type;
    box.appendChild(head);

    if (current.type === "trigger") {
      const select = document.createElement("select");
      MODES.forEach((mode) => {
        const option = document.createElement("option");
        option.value = mode;
        option.textContent = mode;
        if (current.trigger_mode === mode) option.selected = true;
        select.appendChild(option);
      });
      select.addEventListener("change", () => {
        current.trigger_mode = select.value;
        draw();
      });
      box.appendChild(field("trigger_mode", select));
      box.appendChild(field("schedule (cron)", textInput(current.schedule || "", (v) => {
        current.schedule = v;
        draw();
      }, "0 9 * * 1-5")));
      box.appendChild(field("webhook_path", textInput(current.webhook_path || "", (v) => {
        current.webhook_path = v;
        draw();
      }, "/hooks/my-workflow")));
    } else if (current.type === "agent") {
      box.appendChild(field("prompt", textArea(current.prompt || "", (v) => {
        current.prompt = v;
        draw();
      }, 5)));
      box.appendChild(field("profile / bot (optional)", profileSelect(current)));
      const chosen = profileByName(current.profile);
      if (chosen) {
        const runs = document.createElement("p");
        runs.className = "vw-hint";
        runs.textContent = "runs as " + (chosen.label || chosen.name) +
          (chosen.model ? " \u00b7 " + chosen.model : "") +
          (chosen.provider ? " / " + chosen.provider : "");
        box.appendChild(runs);
      }
      box.appendChild(field("model (optional)", textInput(current.model || "", (v) => {
        current.model = v;
      })));
      box.appendChild(field("provider (optional)", textInput(current.provider || "", (v) => {
        current.provider = v;
      })));
    } else if (current.type === "condition") {
      box.appendChild(field("expression", textInput(current.expression || "", (v) => {
        current.expression = v;
        draw();
      }, "out.draft.word_count > 20")));
      const hint = document.createElement("p");
      hint.className = "vw-hint";
      hint.textContent = "Must start with out.<node>.<field> <op> <value>.";
      box.appendChild(hint);
    } else if (current.type === "approval") {
      box.appendChild(field("question", textArea(current.question || "", (v) => {
        current.question = v;
        draw();
      }, 3)));
      box.appendChild(field("options (comma separated)", textInput(
        (current.options || []).join(", "),
        (v) => {
          const list = v.split(",").map((s) => s.trim()).filter(Boolean);
          if (list.length) current.options = list;
          else delete current.options;
          draw();
        },
        "ship, edit"
      )));
    } else if (current.type === "output") {
      const parents = document.createElement("p");
      parents.className = "vw-muted";
      parents.textContent = (current.after || []).length
        ? (current.after || []).join(", ")
        : "(no parents \u2014 this output collects nothing)";
      box.appendChild(field("parents", parents));
      const deliver = document.createElement("select");
      [["", "collect only (no delivery)"],
       ["notification", "notification \u2014 my home channel"],
       ["channel", "channel \u2014 a specific chat"]].forEach((pair) => {
        const option = document.createElement("option");
        option.value = pair[0];
        option.textContent = pair[1];
        if ((current.deliver || "") === pair[0]) option.selected = true;
        deliver.appendChild(option);
      });
      deliver.addEventListener("change", () => {
        if (deliver.value) current.deliver = deliver.value;
        else delete current.deliver;
        buildInspector();
        draw();
      });
      box.appendChild(field("deliver", deliver));
      if (current.deliver === "channel") {
        box.appendChild(field("target", textInput(current.target || "", (v) => {
          current.target = v;
          draw();
        }, "telegram:123456789")));
        const targetHint = document.createElement("p");
        targetHint.className = "vw-hint";
        targetHint.textContent = "<platform>:<chat id>. Leave empty to use the platform's home channel.";
        box.appendChild(targetHint);
      }
    }
  }

  function note(message) {
    el.status.textContent = message || "";
  }

  function showErrors(errors) {
    const list = errors || [];
    if (!list.length) {
      el.errors.textContent = "valid \u00b7 " + graph.nodes.length + " node(s)";
      return;
    }
    el.errors.textContent = list.map((e) => {
      return (e.node ? e.node + ": " : "") + e.field + " \u2014 " + e.msg;
    }).join("\n");
  }

  function addNode(kind, x, y) {
    let index = 0;
    let id;
    do {
      index += 1;
      id = kind + index;
    } while (nodeById(id));
    const fresh = { id: id, type: kind, after: [] };
    if (kind === "trigger") fresh.trigger_mode = "manual";
    if (kind === "agent") fresh.prompt = "";
    if (kind === "condition") fresh.expression = "";
    if (kind === "approval") fresh.question = "";
    if (typeof x === "number" && typeof y === "number") {
      fresh.x = Math.max(0, Math.round(x - NODE_W / 2));
      fresh.y = Math.max(0, Math.round(y - NODE_H / 2));
    } else {
      const slot = graph.nodes.length;
      fresh.x = 30 + (slot % 4) * 196;
      fresh.y = 40 + Math.floor(slot / 4) * 128;
    }
    graph.nodes.push(fresh);
    selected = id;
    selectedEdge = null;
    linkQueue = [id];
    buildInspector();
    draw();
  }

  function currentName() {
    return (el.name.value || "").trim();
  }

  function payloadGraph() {
    return { name: currentName() || "workflow", nodes: clone(graph.nodes) };
  }

  function designPath(name) {
    return "/designs/" + encodeURIComponent(name);
  }

  // ------------------------------------------------------------------ rail
  function button(label, onClick) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "vw-pill";
    b.textContent = label;
    b.addEventListener("click", onClick);
    return b;
  }

  function renderRail() {
    const box = el.designs;
    box.textContent = "";
    if (!designs.length) {
      const empty = document.createElement("p");
      empty.className = "vw-muted";
      empty.textContent = "None yet \u2014 build one and Save.";
      box.appendChild(empty);
      return;
    }
    designs.forEach((name) => {
      const b = button(name, () => open(name));
      b.setAttribute("aria-pressed", name === active ? "true" : "false");
      box.appendChild(b);
    });
  }

  /** Profiles ("bots") for the agent picker. A failure is not fatal: the picker just offers
   *  nothing and the free-text model/provider fields still work. */
  function refreshProfiles() {
    return call("/profiles").then((data) => {
      profiles = (data && data.profiles) || [];
      buildInspector();
    }).catch(() => {
      profiles = [];
    });
  }

  function refreshDesigns() {
    return call("/designs").then((data) => {
      designs = (data && data.designs) || [];
      el.railError.textContent = "";
      renderRail();
    }).catch((err) => {
      el.railError.textContent = explain(err);
    });
  }

  function open(name) {
    call(designPath(name)).then((data) => {
      active = name;
      el.railError.textContent = "";
      loadGraph(data.graph);
      renderRail();
    }).catch((err) => {
      el.railError.textContent = explain(err);
    });
  }

  // ------------------------------------------------------------------- API
  function validateDraft() {
    const name = currentName() || "untitled";
    note("validating\u2026");
    call(designPath(name) + "/validate", {
      method: "POST",
      body: { graph: payloadGraph() },
    }).then((data) => {
      showErrors(data.errors || []);
      note(data.valid ? "valid" : (data.errors || []).length + " problem(s)");
    }).catch((err) => {
      note("");
      showErrors([{ node: "", field: "request", msg: explain(err) }]);
    });
  }

  function saveDesign() {
    const name = currentName();
    if (!name) {
      showErrors([{ node: "", field: "name", msg: "give the design a name first" }]);
      return;
    }
    note("saving\u2026");
    call(designPath(name), {
      method: "POST",
      body: { graph: payloadGraph() },
    }).then((data) => {
      if (!data.ok) {
        showErrors(data.errors || []);
        note("not saved");
        return;
      }
      active = name;
      showErrors([]);
      note("saved " + data.name + " (" + data.nodes + " node(s))");
      refreshDesigns();
    }).catch((err) => {
      note("");
      showErrors([{ node: "", field: "save", msg: explain(err) }]);
    });
  }

  function runDesign() {
    const name = currentName();
    if (!name) {
      showErrors([{ node: "", field: "name", msg: "save the design first" }]);
      return;
    }
    note("running " + name + "\u2026");
    call(designPath(name) + "/run", { method: "POST" }).then((data) => {
      if (data.status === "invalid") {
        showErrors(data.errors || []);
        note("not run");
        return;
      }
      showErrors([]);
      renderRun(data);
    }).catch((err) => {
      note("");
      showErrors([{ node: "", field: "run", msg: explain(err) }]);
    });
  }

  function respond(nodeId, answer) {
    if (!lastRun || !lastRun.run_id) {
      note("no active run");
      return;
    }
    let body = { run_id: lastRun.run_id, node_id: nodeId, answer: answer };
    if (answer && typeof answer === "string" && answer.trim().charAt(0) === "{") {
      // A JSON object is passed as `structured` so downstream conditions can read fields.
      try {
        const parsed = JSON.parse(answer);
        if (parsed && typeof parsed === "object") {
          body = { run_id: lastRun.run_id, node_id: nodeId, structured: parsed, answer: answer };
        }
      } catch (ignored) {
        /* not JSON: send the text */
      }
    }
    note("resuming\u2026");
    call("/runs/" + encodeURIComponent(lastRun.run_id) + "/respond", {
      method: "POST",
      body: body,
    }).then((data) => {
      showErrors([]);
      renderRun(data);
    }).catch((err) => {
      note("");
      el.run.textContent = explain(err);
    });
  }

  // --------------------------------------------------------------- run box
  function line(tag, text, cls) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    node.textContent = text;
    return node;
  }

  /** "sent out \u2192 telegram (\u2026); FAILED out \u2192 \u2026" for every output that delivered. */
  function deliveryLine(result) {
    const list = result.deliveries || [];
    if (!list.length) return null;
    return line("p", "delivery: " + list.map((d) => {
      return (d.ok ? "sent " : "FAILED ") + d.node_id + " \u2192 " + (d.target || "?") +
        (d.detail ? " " + d.detail : "");
    }).join(" \u00b7 "), "vw-muted");
  }

  function renderRun(result) {
    lastRun = result;
    const box = el.run;
    box.textContent = "";
    const status = result.status;
    note(String(status || ""));

    if (status === "awaiting_approval") {
      const pending = result.pending || {};
      box.appendChild(line("h4", "gate " + pending.node_id + ": " + (pending.question || "")));
      if (pending.context) box.appendChild(line("pre", pending.context));
      const options = pending.options || [];
      if (options.length) {
        const row = document.createElement("div");
        options.forEach((option) => {
          row.appendChild(button(option, () => {
            respond(pending.node_id, option);
          }));
        });
        box.appendChild(row);
      } else {
        box.appendChild(line("p", "Type the answer and press Send.", "vw-muted"));
        const free = document.createElement("textarea");
        free.rows = 2;
        box.appendChild(free);
        box.appendChild(button("Send", () => {
          respond(pending.node_id, free.value);
        }));
      }
      return;
    }

    if (status === "awaiting_agent") {
      const step = result.pending || {};
      box.appendChild(line("h4", "agent step " + step.node_id + " is waiting"));
      box.appendChild(line("pre", step.prompt || ""));
      if (step.context) box.appendChild(line("pre", step.context));
      const area = document.createElement("textarea");
      area.rows = 3;
      area.placeholder = "paste the step's output (a JSON object is passed as structured)";
      box.appendChild(area);
      box.appendChild(button("Send result", () => {
        respond(step.node_id, area.value);
      }));
      return;
    }

    if (status === "failed") {
      const error = result.error || {};
      box.appendChild(line("h4", "run failed"));
      box.appendChild(line("pre", (error.node_id ? error.node_id + ": " : "") + (error.msg || "")));
      const failedDelivery = deliveryLine(result);
      if (failedDelivery) box.appendChild(failedDelivery);
      return;
    }

    if (status === "done") {
      const outputs = result.outputs || {};
      box.appendChild(line("h4", "done \u00b7 outputs: " + (Object.keys(outputs).join(", ") || "(none)")));
      if ((result.skipped || []).length) {
        box.appendChild(line("p", "skipped: " + result.skipped.join(", "), "vw-muted"));
      }
      const delivered = deliveryLine(result);
      if (delivered) box.appendChild(delivered);
      box.appendChild(line("pre", JSON.stringify(outputs, null, 2)));
      return;
    }

    box.appendChild(line("h4", String(status || "run")));
    if (result.error) {
      box.appendChild(line("pre", typeof result.error === "string" ? result.error : JSON.stringify(result.error)));
    }
  }

  // ------------------------------------------------------------- wiring up
  function wire() {
    el.name.addEventListener("input", (ev) => {
      graph.name = ev.target.value.trim();
    });
    q('[data-vw="validate"]').addEventListener("click", validateDraft);
    q('[data-vw="save"]').addEventListener("click", saveDesign);
    q('[data-vw="run-now"]').addEventListener("click", runDesign);
    q('[data-vw="connect"]').addEventListener("click", connect);
    q('[data-vw="delete"]').addEventListener("click", removeSelected);
    q('[data-vw="new"]').addEventListener("click", () => {
      active = "";
      el.railError.textContent = "";
      loadGraph(Object.assign(clone(BLANK), { name: "untitled" }));
      renderRail();
    });

    Array.prototype.forEach.call(host.querySelectorAll("[data-kind]"), (b) => {
      const kind = b.getAttribute("data-kind");
      b.addEventListener("click", () => {
        addNode(kind);
      });
      b.addEventListener("dragstart", (ev) => {
        ev.dataTransfer.setData("text/plain", kind);
        ev.dataTransfer.effectAllowed = "copy";
      });
    });

    el.wrap.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "copy";
    });
    el.wrap.addEventListener("drop", (ev) => {
      ev.preventDefault();
      const kind = ev.dataTransfer.getData("text/plain");
      if (KINDS.indexOf(kind) < 0) return;
      const p = svgPoint(ev);
      addNode(kind, p.x, p.y);
    });
  }

  /** Replace the canvas with a stored graph (or a blank one). */
  function loadGraph(next) {
    graph = clone(next && next.nodes ? next : BLANK);
    if (!graph.name) graph.name = "untitled";
    selected = null;
    selectedEdge = null;
    linkQueue = [];
    linkArm = null;
    dragLink = null;
    lastRun = null;
    el.run.textContent = "";
    el.errors.textContent = "";
    note("");
    el.name.value = graph.name;
    layout();
    buildInspector();
    draw();
  }

  wire();
  layout();
  el.name.value = graph.name;
  buildInspector();
  draw();
  renderRail();
  refreshDesigns();
  refreshProfiles();

  return { loadGraph: loadGraph, getGraph: payloadGraph };
}

/**
 * The page component. The SDK exposes no React hooks and the runtime loader maps only
 * `react/jsx-runtime`, so this is a pure-jsx shell whose ref callback mounts the vanilla
 * designer. `mount` is created once (stable identity), so React attaches it on mount and calls
 * it with null on unmount instead of remounting the canvas on every host re-render.
 */
function createWorkflowsPage(call) {
  function mount(node) {
    if (!node || node.__vwDesigner) return;
    node.__vwDesigner = createDesigner(node, call);
  }

  return function WorkflowsPage() {
    return jsx("div", { ref: mount });
  };
}

export default {
  id: "visual-workflow",
  name: "Workflows",
  description:
    "Design and run visual agent workflows \u2014 Trigger, Agent, Condition, Approval and Output nodes on a canvas.",
  register(ctx) {
    // One indirection so every backend call goes through the host's namespace-scoped REST door;
    // it resolves to /api/plugins/visual-workflow (dashboard/plugin_api.py).
    const call = (path, opts) => ctx.rest(path, opts);
    const WorkflowsPage = createWorkflowsPage(call);

    ctx.register({
      id: "workflows-page",
      area: "routes",
      title: "Workflows",
      data: { path: "/workflows" },
      render: () => jsx(WorkflowsPage, {}),
    });

    ctx.register({
      id: "workflows-nav",
      area: "sidebar.nav",
      data: { codicon: "project", label: "Workflows", path: "/workflows" },
    });
  },
};
