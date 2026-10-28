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
    '      <p class="vw-hint">Click two nodes, then Connect.</p>' +
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
    var linkQueue = [];
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
          svg.appendChild(svgEl("line", {
            x1: parent.x + NODE_W / 2, y1: parent.y + NODE_H / 2,
            x2: n.x + NODE_W / 2, y2: n.y + NODE_H / 2,
            stroke: "var(--vw-line)", "stroke-width": 1.5,
          }));
        });
      });

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
      // The queue is "the two most recently clicked nodes", parent first. Clicking a node
      // again must not drop it (that would make click-click-Connect impossible).
      linkQueue = linkQueue.filter(function (x) {
        return x !== id;
      }).concat([id]).slice(-2);
      buildInspector();
      draw();
    }

    function connect() {
      if (linkQueue.length < 2) {
        note("Click two nodes on the canvas, then Connect.");
        return;
      }
      var from = linkQueue[0];
      var target = nodeById(linkQueue[1]);
      if (!target) return;
      target.after = target.after || [];
      if (target.after.indexOf(from) < 0) target.after.push(from);
      note("");
      draw();
    }

    function removeSelected() {
      if (!selected) {
        note("Select a node first.");
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
      linkQueue = [];
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
        return;
      }

      if (status === "done") {
        var outputs = result.outputs || {};
        box.appendChild(line("h4", "done \u00b7 outputs: " + (Object.keys(outputs).join(", ") || "(none)")));
        if ((result.skipped || []).length) {
          box.appendChild(line("p", "skipped: " + result.skipped.join(", "), "vw-muted"));
        }
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
      linkQueue = [];
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

    useEffect(function () {
      if (!hostRef.current) return undefined;
      designerRef.current = createDesigner(hostRef.current, {
        fetchJSON: fetchJSON,
        onSaved: refresh,
      });
      refresh();
      return function () {
        designerRef.current = null;
      };
    }, [refresh]);

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
