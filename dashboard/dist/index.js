/**
 * Hermes Workflows — dashboard plugin.
 *
 * Designer canvas (palette · SVG graph · inspector) ported from widgets/designer.html, wrapped
 * in a React tab so the dashboard can show it at /workflows. Plain IIFE, no build step: React,
 * the hooks and the auth-aware JSON client all come from window.__HERMES_PLUGIN_SDK__.
 *
 * Backend is this plugin's own router at /api/plugins/visual-workflow/ (dashboard/plugin_api.py):
 *   GET  /designs                     saved design names
 *   GET  /designs/{name}              one graph
 *   POST /designs/{name}              validate + save a graph
 *   POST /designs/{name}/validate     validate a saved design or a draft {"graph": ...}
 *   POST /designs/{name}/run          run now, until done or paused
 *   POST /runs/{run_id}/respond       answer an approval gate / a pending agent step
 */
(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  // No SDK means this bundle was loaded by something that is not the Hermes dashboard:
  // bail out instead of throwing on the first hook access.
  if (!SDK) {
    if (window.console) window.console.warn("[visual-workflow] plugin SDK missing; Workflows tab disabled");
    return;
  }
  var PLUGINS = window.__HERMES_PLUGINS__;
  if (!PLUGINS || typeof PLUGINS.register !== "function") return;

  var React = SDK.React;
  var h = React.createElement;
  var hooks = SDK.hooks || {};
  var useState = hooks.useState;
  var useEffect = hooks.useEffect;
  var useRef = hooks.useRef;
  var useCallback = hooks.useCallback;
  var fetchJSON = SDK.fetchJSON;

  var API = "/api/plugins/visual-workflow";
  var SVG_NS = "http://www.w3.org/2000/svg";
  var KINDS = ["trigger", "agent", "condition", "approval", "output"];
  var MODES = ["manual", "schedule", "webhook"];
  var NODE_W = 168;
  var NODE_H = 56;
  var PORT_R = 5;

  // ---- edge geometry (identical in dashboard/dist/index.js, widgets/designer.html and
  // desktop/plugin.js: no build step, so the block is copied rather than imported).
  // Every node has an OUTPUT port on its right edge and — except a trigger, which can have
  // no parents — an INPUT port on its left edge. An edge is drawn from the parent's output
  // port to the child's input port, so the arrow-less curve reads as a direction.
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
    var p = outPort(parent);
    var q = inPort(child);
    var bend = Math.max(30, Math.abs(q.x - p.x) / 2);
    return "M" + p.x + "," + p.y +
      "C" + (p.x + bend) + "," + p.y + " " + (q.x - bend) + "," + q.y + " " + q.x + "," + q.y;
  }

  // JSON (not a JS literal) so the base graph stays the same shape the tools accept.
  var BLANK_JSON =
    '{"name":"untitled","nodes":[{"id":"trigger1","type":"trigger","trigger_mode":"manual","after":[]}]}';
  var BLANK = JSON.parse(BLANK_JSON);

  // The host theme this tab renders under (LENS_0) has NO global --card/--border/
  // --muted-foreground/--accent, and its --foreground is transparent (alpha 0). Derive the
  // whole palette from tokens that DO exist, scoped to the shell so the rest of the
  // dashboard is untouched.
  var CSS = [
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

  var TEMPLATE =
    '<div class="vw-app">' +
    '  <div class="vw-bar">' +
    '    <input class="vw-grow" data-vw="name" type="text" value="untitled" aria-label="design name">' +
    '    <button class="vw-pill" type="button" data-vw="validate">Validate</button>' +
    '    <button class="vw-pill" type="button" data-vw="save">Save</button>' +
    '    <button class="vw-pill" type="button" data-vw="run-now">Run</button>' +
    '    <button class="vw-pill" type="button" data-vw="connect">Connect</button>' +
    '    <button class="vw-pill" type="button" data-vw="delete">Delete</button>' +
    '    <span class="vw-muted" data-vw="status"></span>' +
    '  </div>' +
    '  <div class="vw-main">' +
    '    <div class="vw-palette">' +
    '      <button class="vw-pill" type="button" draggable="true" data-kind="trigger">Trigger</button>' +
    '      <button class="vw-pill" type="button" draggable="true" data-kind="agent">Agent</button>' +
    '      <button class="vw-pill" type="button" draggable="true" data-kind="condition">Condition</button>' +
    '      <button class="vw-pill" type="button" draggable="true" data-kind="approval">Approval</button>' +
    '      <button class="vw-pill" type="button" draggable="true" data-kind="output">Output</button>' +
    '      <p class="vw-hint">Drag from a node&rsquo;s right port to another node&rsquo;s left port. Click an edge, then Delete, to cut it.</p>' +
    '    </div>' +
    '    <div class="vw-wrap" data-vw="wrap">' +
    '      <svg class="vw-canvas" data-vw="canvas" width="900" height="560" role="img" aria-label="workflow canvas"></svg>' +
    '    </div>' +
    '    <div class="vw-inspector" data-vw="inspector"></div>' +
    '  </div>' +
    '  <div class="vw-run" data-vw="run"></div>' +
    '  <pre class="vw-errors" data-vw="errors"></pre>' +
    "</div>";

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  /** ``"422: {...}"`` (SDK fetchJSON) -> the server's ``detail`` text. */
  function explain(err) {
    var text = err && err.message ? err.message : String(err);
    var i = text.indexOf(": ");
    if (i > 0 && /^\d{3}$/.test(text.slice(0, i))) {
      var body = text.slice(i + 2);
      try {
        var parsed = JSON.parse(body);
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
  var PAINT_ATTRS = { fill: 1, stroke: 1, "stop-color": 1 };

  function svgEl(name, attrs) {
    var el = document.createElementNS(SVG_NS, name);
    Object.keys(attrs || {}).forEach(function (key) {
      var value = attrs[key];
      if (PAINT_ATTRS[key] && String(value).indexOf("var(") >= 0) {
        el.style.setProperty(key, value);
      } else {
        el.setAttribute(key, value);
      }
    });
    return el;
  }

  /**
   * Mount the designer into *host* and return its controller.
   *
   * The canvas is plain DOM/SVG (the same drawing and drag logic the widget uses); React only
   * owns the tab shell around it, so no graph state lives in the React tree.
   */
  function createDesigner(host, options) {
    var call = options.fetchJSON || fetchJSON;
    var onSaved = options.onSaved || function () {};

    host.innerHTML = TEMPLATE;
    var q = function (sel) {
      return host.querySelector(sel);
    };
    var el = {
      name: q('[data-vw="name"]'),
      canvas: q('[data-vw="canvas"]'),
      wrap: q('[data-vw="wrap"]'),
      inspector: q('[data-vw="inspector"]'),
      errors: q('[data-vw="errors"]'),
      status: q('[data-vw="status"]'),
      run: q('[data-vw="run"]'),
    };

    var graph = clone(BLANK);
    var selected = null;
    var selectedEdge = null;
    var linkQueue = [];
    var linkArm = null;   // source node id after a click on an output port
    var dragLink = null;  // live drag from an output port: {from, x1, y1, x2, y2}
    var lastRun = null;

    function nodeById(id) {
      var hits = graph.nodes.filter(function (n) {
        return n.id === id;
      });
      return hits[0] || null;
    }

    function layout() {
      graph.nodes.forEach(function (n, i) {
        if (typeof n.x !== "number" || typeof n.y !== "number") {
          n.x = 30 + (i % 4) * 196;
          n.y = 40 + Math.floor(i / 4) * 128;
        }
      });
    }

    function preview(n) {
      var text =
        n.type === "agent" ? n.prompt || "" :
        n.type === "condition" ? n.expression || "" :
        n.type === "approval" ? n.question || "" :
        n.type === "trigger" ? (n.trigger_mode || "") + (n.schedule ? " " + n.schedule : "") :
        (n.after || []).join(", ");
      text = String(text).replace(/\s+/g, " ").trim();
      return text.length > 26 ? text.slice(0, 25) + "\u2026" : text;
    }

    function draw() {
      var svg = el.canvas;
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      var byId = {};
      graph.nodes.forEach(function (n) {
        byId[n.id] = n;
      });

      graph.nodes.forEach(function (n) {
        (n.after || []).forEach(function (dep) {
          var parent = byId[dep];
          if (!parent) return;
          var d = edgePath(parent, n);
          var on = selectedEdge === edgeKey(parent.id, n.id);
          var path = svgEl("path", { d: d, "class": on ? "vw-edge vw-edge-on" : "vw-edge" });
          // A 1.6px stroke is nearly impossible to hit; the transparent twin is the target.
          var hit = svgEl("path", { d: d, "class": "vw-edge-hit", "data-edge": edgeKey(parent.id, n.id) });
          function cut(ev) {
            ev.stopPropagation();
            selectedEdge = edgeKey(parent.id, n.id);
            selected = null;
            buildInspector();
            draw();
          }
          path.addEventListener("click", cut);
          hit.addEventListener("click", cut);
          hit.addEventListener("dblclick", function (ev) {
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
          "class": "vw-ghost",
        }));
      }

      graph.nodes.forEach(function (n) {
        var isSelected = n.id === selected;
        var queued = linkQueue.indexOf(n.id) >= 0;
        var g = svgEl("g", {
          transform: "translate(" + n.x + "," + n.y + ")",
          "class": "vw-node",
          "data-id": n.id,
        });
        g.appendChild(svgEl("rect", {
          width: NODE_W, height: NODE_H, rx: 6,
          fill: "var(--vw-node)",
          stroke: isSelected || queued ? "var(--vw-accent)" : "var(--vw-line)",
          "stroke-width": isSelected ? 2 : 1,
        }));
        var kind = svgEl("text", { x: 10, y: 16, "font-size": 9, fill: "var(--vw-dim)" });
        kind.textContent = String(n.type).toUpperCase();
        var id = svgEl("text", { x: 10, y: 32, "font-size": 12, fill: "var(--vw-ink)" });
        id.textContent = n.id;
        var sub = svgEl("text", { x: 10, y: 46, "font-size": 10, fill: "var(--vw-dim)" });
        sub.textContent = preview(n);
        g.appendChild(kind);
        g.appendChild(id);
        g.appendChild(sub);

        var out = svgEl("circle", {
          cx: NODE_W, cy: NODE_H / 2, r: PORT_R, "class": "vw-port",
          "data-port": "out", "data-id": n.id,
        });
        out.addEventListener("mousedown", function (ev) {
          // The port owns the gesture; without this the node drag starts instead.
          ev.stopPropagation();
          ev.preventDefault();
          beginLink(n, ev);
        });
        g.appendChild(out);

        if (n.type !== "trigger") {
          var inp = svgEl("circle", {
            cx: 0, cy: NODE_H / 2, r: PORT_R, "class": "vw-port",
            "data-port": "in", "data-id": n.id,
          });
          inp.addEventListener("mousedown", function (ev) {
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
      var svg = el.canvas;
      var pt = svg.createSVGPoint();
      pt.x = ev.clientX;
      pt.y = ev.clientY;
      var matrix = svg.getScreenCTM();
      return matrix ? pt.matrixTransform(matrix.inverse()) : { x: ev.clientX, y: ev.clientY };
    }

    function wireNode(g, n) {
      g.addEventListener("mousedown", function (ev) {
        if (ev.button !== 0) return;
        // A port handler already claimed this press (stopPropagation also covers it, but a
        // port inside a child <g> must never drag the node).
        if (ev.target && ev.target.getAttribute && ev.target.getAttribute("data-port")) return;
        ev.preventDefault();
        var start = svgPoint(ev);
        var offset = { x: start.x - n.x, y: start.y - n.y };
        var moved = false;
        function onMove(moveEv) {
          var p = svgPoint(moveEv);
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
      linkQueue = linkQueue.filter(function (x) {
        return x !== id;
      }).concat([id]).slice(-2);
      buildInspector();
      draw();
    }

    /** The node under a canvas point, by geometry (DOM hit-testing would trip over the
     *  edge hit-areas and the drag ghost stacked above the node). */
    function nodeIdAtPoint(p) {
      var PAD = 6;
      for (var i = graph.nodes.length - 1; i >= 0; i -= 1) {
        var n = graph.nodes[i];
        if (p.x >= n.x - PAD && p.x <= n.x + NODE_W + PAD &&
            p.y >= n.y - PAD && p.y <= n.y + NODE_H + PAD) return n.id;
      }
      return null;
    }

    /** Would making *to* depend on *from* close a loop? Walk up from *from*. */
    function createsCycle(from, to) {
      var seen = {};
      var stack = [from];
      while (stack.length) {
        var id = stack.pop();
        if (id === to) return true;
        if (seen[id]) continue;
        seen[id] = 1;
        var n = nodeById(id);
        if (n) stack = stack.concat(n.after || []);
      }
      return false;
    }

    /** Drag started on *n*'s output port: follow the pointer, connect on release. */
    function beginLink(n, ev) {
      var start = svgPoint(ev);
      var origin = outPort(n);
      var moved = false;
      linkArm = null;
      dragLink = { from: n.id, x1: origin.x, y1: origin.y, x2: start.x, y2: start.y };
      draw();
      function onMove(moveEv) {
        var p = svgPoint(moveEv);
        if (Math.abs(p.x - start.x) > 3 || Math.abs(p.y - start.y) > 3) moved = true;
        dragLink.x2 = p.x;
        dragLink.y2 = p.y;
        draw();
      }
      function onUp(upEv) {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        var from = dragLink.from;
        dragLink = null;
        if (moved) {
          var targetId = nodeIdAtPoint(svgPoint(upEv));
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
      var source = nodeById(from);
      var target = nodeById(to);
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
      var target = nodeById(to);
      if (target) {
        target.after = (target.after || []).filter(function (dep) {
          return dep !== from;
        });
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
        var parts = selectedEdge.split(">");
        cutEdge(parts[0], parts[1]);
        return;
      }
      if (!selected) {
        note("Select a node or an edge first.");
        return;
      }
      var removed = selected;
      graph.nodes = graph.nodes.filter(function (n) {
        return n.id !== removed;
      });
      graph.nodes.forEach(function (n) {
        n.after = (n.after || []).filter(function (dep) {
          return dep !== removed;
        });
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
      var wrap = document.createElement("div");
      var label = document.createElement("div");
      label.className = "vw-label";
      label.textContent = labelText;
      wrap.appendChild(label);
      wrap.appendChild(control);
      return wrap;
    }

    function textInput(value, onInput, placeholder) {
      var input = document.createElement("input");
      input.type = "text";
      input.value = value || "";
      if (placeholder) input.placeholder = placeholder;
      input.addEventListener("input", function () {
        onInput(input.value);
      });
      return input;
    }

    function textArea(value, onInput, rows) {
      var area = document.createElement("textarea");
      area.rows = rows || 4;
      area.value = value || "";
      area.addEventListener("input", function () {
        onInput(area.value);
      });
      return area;
    }

    /** Host profiles ("bots") as ``[{name, label, model, provider}]``; empty when the
     *  backend could not list them, in which case the picker degrades to a placeholder. */
    var profiles = options.profiles || [];

    function profileByName(name) {
      if (!name) return null;
      var hits = profiles.filter(function (p) {
        return p.name === name;
      });
      return hits[0] || null;
    }

    function profileSelect(current) {
      var select = document.createElement("select");
      var blank = document.createElement("option");
      blank.value = "";
      blank.textContent = profiles.length ? "\u2014 host default \u2014" : "\u2014 no profiles listed \u2014";
      select.appendChild(blank);
      var known = false;
      profiles.forEach(function (p) {
        var option = document.createElement("option");
        option.value = p.name;
        option.textContent = p.label && p.label !== p.name ? p.label + " (" + p.name + ")" : p.name;
        if (p.name === current.profile) {
          option.selected = true;
          known = true;
        }
        select.appendChild(option);
      });
      if (current.profile && !known) {
        // A saved design can name a profile that was renamed or removed: keep the value
        // visible instead of silently resetting it.
        var stale = document.createElement("option");
        stale.value = current.profile;
        stale.textContent = current.profile + " (not found)";
        stale.selected = true;
        select.appendChild(stale);
      }
      select.addEventListener("change", function () {
        if (select.value) current.profile = select.value;
        else delete current.profile;
        buildInspector();
        draw();
      });
      return select;
    }

    function buildInspector() {
      var box = el.inspector;
      box.textContent = "";
      var current = selected ? nodeById(selected) : null;
      if (!current) {
        var empty = document.createElement("p");
        empty.className = "vw-muted";
        empty.textContent = "Select a node to edit it.";
        box.appendChild(empty);
        return;
      }
      var head = document.createElement("p");
      head.className = "vw-muted";
      head.textContent = current.id + " \u00b7 " + current.type;
      box.appendChild(head);

      if (current.type === "trigger") {
        var select = document.createElement("select");
        MODES.forEach(function (mode) {
          var option = document.createElement("option");
          option.value = mode;
          option.textContent = mode;
          if (current.trigger_mode === mode) option.selected = true;
          select.appendChild(option);
        });
        select.addEventListener("change", function () {
          current.trigger_mode = select.value;
          draw();
        });
        box.appendChild(field("trigger_mode", select));
        box.appendChild(field("schedule (cron)", textInput(current.schedule || "", function (v) {
          current.schedule = v;
          draw();
        }, "0 9 * * 1-5")));
        box.appendChild(field("webhook_path", textInput(current.webhook_path || "", function (v) {
          current.webhook_path = v;
          draw();
        }, "/hooks/my-workflow")));
      } else if (current.type === "agent") {
        box.appendChild(field("prompt", textArea(current.prompt || "", function (v) {
          current.prompt = v;
          draw();
        }, 5)));
        box.appendChild(field("profile / bot (optional)", profileSelect(current)));
        var chosen = profileByName(current.profile);
        if (chosen) {
          var runs = document.createElement("p");
          runs.className = "vw-hint";
          runs.textContent = "runs as " + (chosen.label || chosen.name) +
            (chosen.model ? " \u00b7 " + chosen.model : "") +
            (chosen.provider ? " / " + chosen.provider : "");
          box.appendChild(runs);
        }
        box.appendChild(field("model (optional)", textInput(current.model || "", function (v) {
          current.model = v;
        })));
        box.appendChild(field("provider (optional)", textInput(current.provider || "", function (v) {
          current.provider = v;
        })));
      } else if (current.type === "condition") {
        box.appendChild(field("expression", textInput(current.expression || "", function (v) {
          current.expression = v;
          draw();
        }, "out.draft.word_count > 20")));
        var hint = document.createElement("p");
        hint.className = "vw-hint";
        hint.textContent = "Must start with out.<node>.<field> <op> <value>.";
        box.appendChild(hint);
      } else if (current.type === "approval") {
        box.appendChild(field("question", textArea(current.question || "", function (v) {
          current.question = v;
          draw();
        }, 3)));
        box.appendChild(field("options (comma separated)", textInput(
          (current.options || []).join(", "),
          function (v) {
            var list = v.split(",").map(function (s) {
              return s.trim();
            }).filter(Boolean);
            if (list.length) current.options = list;
            else delete current.options;
            draw();
          },
          "ship, edit"
        )));
      } else if (current.type === "output") {
        var parents = document.createElement("p");
        parents.className = "vw-muted";
        parents.textContent = (current.after || []).length
          ? (current.after || []).join(", ")
          : "(no parents \u2014 this output collects nothing)";
        box.appendChild(field("parents", parents));
        var deliver = document.createElement("select");
        [["", "collect only (no delivery)"],
         ["notification", "notification \u2014 my home channel"],
         ["channel", "channel \u2014 a specific chat"]].forEach(function (pair) {
          var option = document.createElement("option");
          option.value = pair[0];
          option.textContent = pair[1];
          if ((current.deliver || "") === pair[0]) option.selected = true;
          deliver.appendChild(option);
        });
        deliver.addEventListener("change", function () {
          if (deliver.value) current.deliver = deliver.value;
          else delete current.deliver;
          buildInspector();
          draw();
        });
        box.appendChild(field("deliver", deliver));
        if (current.deliver === "channel") {
          box.appendChild(field("target", textInput(current.target || "", function (v) {
            current.target = v;
            draw();
          }, "telegram:123456789")));
          var targetHint = document.createElement("p");
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
      var list = errors || [];
      if (!list.length) {
        el.errors.textContent = "valid \u00b7 " + graph.nodes.length + " node(s)";
        return;
      }
      el.errors.textContent = list.map(function (e) {
        return (e.node ? e.node + ": " : "") + e.field + " \u2014 " + e.msg;
      }).join("\n");
    }

    function addNode(kind, x, y) {
      var index = 0;
      var id;
      do {
        index += 1;
        id = kind + index;
      } while (nodeById(id));
      var fresh = { id: id, type: kind, after: [] };
      if (kind === "trigger") fresh.trigger_mode = "manual";
      if (kind === "agent") fresh.prompt = "";
      if (kind === "condition") fresh.expression = "";
      if (kind === "approval") fresh.question = "";
      if (typeof x === "number" && typeof y === "number") {
        fresh.x = Math.max(0, Math.round(x - NODE_W / 2));
        fresh.y = Math.max(0, Math.round(y - NODE_H / 2));
      } else {
        var slot = graph.nodes.length;
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

    // ------------------------------------------------------------------ API
    function path(name) {
      return API + "/designs/" + encodeURIComponent(name);
    }

    function validateDraft() {
      var name = currentName() || "untitled";
      note("validating\u2026");
      call(path(name) + "/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ graph: payloadGraph() }),
      }).then(function (data) {
        showErrors(data.errors || []);
        note(data.valid ? "valid" : (data.errors || []).length + " problem(s)");
      }).catch(function (err) {
        note("");
        showErrors([{ node: "", field: "request", msg: explain(err) }]);
      });
    }

    function saveDesign() {
      var name = currentName();
      if (!name) {
        showErrors([{ node: "", field: "name", msg: "give the design a name first" }]);
        return;
      }
      note("saving\u2026");
      call(path(name), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ graph: payloadGraph() }),
      }).then(function (data) {
        if (!data.ok) {
          showErrors(data.errors || []);
          note("not saved");
          return;
        }
        showErrors([]);
        note("saved " + data.name + " (" + data.nodes + " node(s))");
        onSaved();
      }).catch(function (err) {
        note("");
        showErrors([{ node: "", field: "save", msg: explain(err) }]);
      });
    }

    function runDesign() {
      var name = currentName();
      if (!name) {
        showErrors([{ node: "", field: "name", msg: "save the design first" }]);
        return;
      }
      note("running " + name + "\u2026");
      call(path(name) + "/run", { method: "POST" }).then(function (data) {
        if (data.status === "invalid") {
          showErrors(data.errors || []);
          note("not run");
          return;
        }
        showErrors([]);
        renderRun(data);
      }).catch(function (err) {
        note("");
        showErrors([{ node: "", field: "run", msg: explain(err) }]);
      });
    }

    function respond(nodeId, answer) {
      if (!lastRun || !lastRun.run_id) {
        note("no active run");
        return;
      }
      var body = { run_id: lastRun.run_id, node_id: nodeId, answer: answer };
      if (answer && typeof answer === "string" && answer.trim().charAt(0) === "{") {
        // A JSON object is passed as `structured` so downstream conditions can read fields.
        try {
          var parsed = JSON.parse(answer);
          if (parsed && typeof parsed === "object") body = { run_id: lastRun.run_id, node_id: nodeId, structured: parsed, answer: answer };
        } catch (ignored) {
          /* not JSON: send the text */
        }
      }
      note("resuming\u2026");
      call(API + "/runs/" + encodeURIComponent(lastRun.run_id) + "/respond", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then(function (data) {
        showErrors([]);
        renderRun(data);
      }).catch(function (err) {
        note("");
        el.run.textContent = explain(err);
      });
    }

    // --------------------------------------------------------------- run box
    function line(tag, text, cls) {
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      node.textContent = text;
      return node;
    }

    function button(label, onClick) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "vw-pill";
      b.textContent = label;
      b.addEventListener("click", onClick);
      return b;
    }

    /** "sent out \u2192 telegram (\u2026); FAILED out \u2192 \u2026" for every output that delivered. */
    function deliveryLine(result) {
      var list = result.deliveries || [];
      if (!list.length) return null;
      return line("p", "delivery: " + list.map(function (d) {
        return (d.ok ? "sent " : "FAILED ") + d.node_id + " \u2192 " + (d.target || "?") +
          (d.detail ? " " + d.detail : "");
      }).join(" \u00b7 "), "vw-muted");
    }

    function renderRun(result) {
      lastRun = result;
      var box = el.run;
      box.textContent = "";
      var status = result.status;
      note(String(status || ""));

      if (status === "awaiting_approval") {
        var pending = result.pending || {};
        box.appendChild(line("h4", "gate " + pending.node_id + ": " + (pending.question || "")));
        if (pending.context) box.appendChild(line("pre", pending.context));
        var options = pending.options || [];
        if (options.length) {
          var row = document.createElement("div");
          options.forEach(function (option) {
            row.appendChild(button(option, function () {
              respond(pending.node_id, option);
            }));
          });
          box.appendChild(row);
        } else {
          box.appendChild(line("p", "Type the answer and press Send.", "vw-muted"));
          var free = document.createElement("textarea");
          free.rows = 2;
          box.appendChild(free);
          box.appendChild(button("Send", function () {
            respond(pending.node_id, free.value);
          }));
        }
        return;
      }

      if (status === "awaiting_agent") {
        var step = result.pending || {};
        box.appendChild(line("h4", "agent step " + step.node_id + " is waiting"));
        box.appendChild(line("pre", step.prompt || ""));
        if (step.context) box.appendChild(line("pre", step.context));
        var area = document.createElement("textarea");
        area.rows = 3;
        area.placeholder = "paste the step's output (a JSON object is passed as structured)";
        box.appendChild(area);
        box.appendChild(button("Send result", function () {
          respond(step.node_id, area.value);
        }));
        return;
      }

      if (status === "failed") {
        var error = result.error || {};
        box.appendChild(line("h4", "run failed"));
        box.appendChild(line("pre", (error.node_id ? error.node_id + ": " : "") + (error.msg || "")));
        var failedDelivery = deliveryLine(result);
        if (failedDelivery) box.appendChild(failedDelivery);
        return;
      }

      if (status === "done") {
        var outputs = result.outputs || {};
        box.appendChild(line("h4", "done \u00b7 outputs: " + (Object.keys(outputs).join(", ") || "(none)")));
        if ((result.skipped || []).length) {
          box.appendChild(line("p", "skipped: " + result.skipped.join(", "), "vw-muted"));
        }
        var delivered = deliveryLine(result);
        if (delivered) box.appendChild(delivered);
        box.appendChild(line("pre", JSON.stringify(outputs, null, 2)));
        return;
      }

      box.appendChild(line("h4", String(status || "run")));
      if (result.error) box.appendChild(line("pre", typeof result.error === "string" ? result.error : JSON.stringify(result.error)));
    }

    // ------------------------------------------------------------- wiring up
    function wire() {
      el.name.addEventListener("input", function (ev) {
        graph.name = ev.target.value.trim();
      });
      q('[data-vw="validate"]').addEventListener("click", validateDraft);
      q('[data-vw="save"]').addEventListener("click", saveDesign);
      q('[data-vw="run-now"]').addEventListener("click", runDesign);
      q('[data-vw="connect"]').addEventListener("click", connect);
      q('[data-vw="delete"]').addEventListener("click", removeSelected);

      Array.prototype.forEach.call(host.querySelectorAll("[data-kind]"), function (b) {
        var kind = b.getAttribute("data-kind");
        b.addEventListener("click", function () {
          addNode(kind);
        });
        b.addEventListener("dragstart", function (ev) {
          ev.dataTransfer.setData("text/plain", kind);
          ev.dataTransfer.effectAllowed = "copy";
        });
      });

      el.wrap.addEventListener("dragover", function (ev) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "copy";
      });
      el.wrap.addEventListener("drop", function (ev) {
        ev.preventDefault();
        var kind = ev.dataTransfer.getData("text/plain");
        if (KINDS.indexOf(kind) < 0) return;
        var p = svgPoint(ev);
        addNode(kind, p.x, p.y);
      });
    }

    wire();
    layout();
    el.name.value = graph.name;
    buildInspector();
    draw();

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

    return {
      loadGraph: loadGraph,
      /** Replace the profile/bot list the agent inspector offers. */
      setProfiles: function (list) {
        profiles = Array.isArray(list) ? list : [];
        buildInspector();
      },
      /** The draft graph as it would be sent to the backend. */
      getGraph: payloadGraph,
      newDesign: function (name) {
        var blank = clone(BLANK);
        blank.name = name || "untitled";
        loadGraph(blank);
      },
    };
  }

  // ---------------------------------------------------------------- React tab
  function WorkflowsTab() {
    var hostRef = useRef(null);
    var designerRef = useRef(null);
    var [designs, setDesigns] = useState([]);
    var [active, setActive] = useState("");
    var [error, setError] = useState("");

    var refresh = useCallback(function () {
      return fetchJSON(API + "/designs").then(function (data) {
        setDesigns((data && data.designs) || []);
      }).catch(function (err) {
        setError(explain(err));
      });
    }, []);

    // Profiles ("bots") are listed once per mount; a failure is not fatal — the picker
    // simply has nothing to offer and the free-text model/provider fields still work.
    var loadProfiles = useCallback(function () {
      return fetchJSON(API + "/profiles").then(function (data) {
        if (designerRef.current) designerRef.current.setProfiles((data && data.profiles) || []);
      }).catch(function () {
        if (designerRef.current) designerRef.current.setProfiles([]);
      });
    }, []);

    useEffect(function () {
      if (!hostRef.current) return undefined;
      designerRef.current = createDesigner(hostRef.current, {
        fetchJSON: fetchJSON,
        onSaved: refresh,
      });
      refresh();
      loadProfiles();
      return function () {
        designerRef.current = null;
      };
    }, [refresh, loadProfiles]);

    function open(name) {
      setActive(name);
      setError("");
      fetchJSON(API + "/designs/" + encodeURIComponent(name)).then(function (data) {
        if (designerRef.current) designerRef.current.loadGraph(data.graph);
      }).catch(function (err) {
        setError(explain(err));
      });
    }

    function blank() {
      setActive("");
      setError("");
      if (designerRef.current) designerRef.current.newDesign("untitled");
    }

    var rail = [
      h("p", { key: "title", className: "vw-rail-title" }, "Saved workflows"),
      designs.length
        ? h("div", { key: "list", className: "vw-list" }, designs.map(function (name) {
          return h("button", {
            key: name,
            type: "button",
            className: "vw-pill",
            "aria-pressed": name === active ? "true" : "false",
            onClick: function () {
              open(name);
            },
          }, name);
        }))
        : h("p", { key: "empty", className: "vw-muted" }, "None yet \u2014 build one and Save."),
      h("button", { key: "new", type: "button", className: "vw-pill", onClick: blank }, "New design"),
      error ? h("p", { key: "err", className: "vw-error" }, error) : null,
    ];

    return h(
      "div",
      { className: "vw-shell" },
      h("style", null, CSS),
      h("div", { className: "vw-rail" }, rail),
      h("div", { className: "vw-stage", ref: hostRef })
    );
  }

  PLUGINS.register("visual-workflow", WorkflowsTab);
})();
