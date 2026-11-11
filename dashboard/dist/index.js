/**
 * Hermes Workflows — dashboard plugin.
 *
 * Designer canvas (top node bar · SVG graph · collapsible inspector) ported from
 * widgets/designer.html, wrapped
 * in a React tab so the dashboard can show it at /workflows. Plain IIFE, no build step: React,
 * the hooks and the auth-aware JSON client all come from window.__HERMES_PLUGIN_SDK__.
 *
 * Backend is this plugin's own router at /api/plugins/visual-workflow/ (dashboard/plugin_api.py):
 *   GET  /designs                     saved design names
 *   GET  /designs/templates           built-in designs shipped in examples/
 *   GET  /designs/{name}              one graph
 *   POST /designs/{name}              validate + save a graph
 *   POST /designs/{name}/validate     validate a saved design or a draft {"graph": ...}
 *   POST /designs/{name}/run          run now, until done or paused
 *   POST /runs/{run_id}/respond       answer an approval gate / a pending agent step
 *                                     (agent_generate: true lets the host agent produce it)
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
  // A sticky note: legal canvas content, never a step. `KINDS` stays the five runnable kinds
  // (the palette list below adds the note), so nothing that validates or converts a workflow
  // can mistake an annotation for work. Mirrors NOTE_KIND in visual_workflow_hermes/schema.py.
  var NOTE = "note";
  var NOTE_COLORS = ["yellow", "blue", "green", "red"];
  var PALETTE = KINDS.concat([NOTE]);
  var MODES = ["manual", "schedule"];

  // ---- tooltips -------------------------------------------------------------
  // One table, one wording, all three surfaces (dashboard/dist/index.js, desktop/plugin.js,
  // widgets/designer.html). A native `title` is the smallest mechanism that works in a React
  // tab, inside SVG and in a standalone HTML file alike; tests/test_tooltips.py asserts every
  // node kind and every inspector option has a real sentence here.
  var TIPS = {
    trigger: "Starts the run: by hand when you press Run, or on a Hermes schedule you pick.",
    agent: "Asks a bot to do one step and waits for its reply.",
    condition: "Compares a field from an earlier step and skips the branch when the test fails.",
    approval: "Pauses the run and asks a person to choose or type an answer.",
    output: "Collects the results, and can send them to one of your chats.",
    note: "A label for you or a teammate: it sits on the canvas and never runs.",
    "trigger.trigger_mode": "How the run starts: manual (you press Run) or schedule (a real Hermes cron job).",
    "trigger.preset": "Pick a schedule in plain words: every day, Monday to Friday, once a week, every hour, or advanced cron.",
    "trigger.time": "Local time of day for the schedule, 24-hour HH:MM (e.g. 09:30).",
    "trigger.weekday": "Day of the week a weekly schedule runs on.",
    "trigger.schedule": "The cron expression actually saved: minute hour day-of-month month weekday \u2014 0 9 * * 1-5 is 09:00 Monday to Friday.",
    "agent.prompt": "What this step should do; the reply becomes out.<node>.text for later steps.",
    "agent.profile": "Which bot runs the step; host default uses the bot you have active.",
    "agent.model": "Model override for this step only; empty keeps the bot's own model.",
    "agent.retries": "How many extra tries the step gets when the bot fails before the run gives up (0 to 3).",
    "condition.expression": "A test like out.draft.word_count > 20 \u2014 start with out.<node>.<field>, then one of > >= < <= == !=.",
    "approval.question": "The question the person sees; the run waits here until they answer.",
    "approval.context": "The material the person is deciding on, shown with the question when the run pauses.",
    "approval.options": "Answers offered as buttons, comma separated (e.g. ship, edit); empty means free text.",
    "approval.timeout": "How long to wait for a person before the gate expires, in minutes; empty waits forever.",
    "approval.on_timeout": "What an expired gate does: reject fails the run, escalate flags it for a person.",
    "output.parents": "Steps whose results this output collects \u2014 connect an edge instead of typing here.",
    "output.send_to": "One choice: collect only, a home channel for a notification, or one specific chat.",
    "output.target": "Where to send it: platform:chat id like telegram:8522302999, or just the platform for its home channel.",
    "note.text": "What the sticky says; it is only for the person reading the canvas.",
    "note.color": "Tint for the sticky; it is a reading aid, not part of the run.",
    "schedule.save": "Create or update the real Hermes cron job that replays this saved workflow.",
    "bar.name": "Name this workflow is saved and run under.",
    "bar.templates": "Start from a built-in workflow: it loads onto the canvas, and Save stores it under your own name.",
    "bar.new": "Start from an empty canvas.",
    "bar.validate": "Check the graph without saving it.",
    "bar.save": "Validate and store the workflow.",
    "bar.run": "Save-free run now: advance until it finishes or pauses at a gate.",
    "bar.delete": "Delete the selected node, or cut the selected edge.",
    "presets.daily": "Runs once every day at the time you pick.",
    "presets.weekdays": "Runs Monday to Friday at the time you pick.",
    "presets.weekly": "Runs once a week on the day and time you pick.",
    "presets.hourly": "Runs every hour at the minute you pick.",
    "presets.custom": "Type a cron expression yourself; it is checked as you type.",
    "schedules.pause": "Stop the schedule from firing; the saved workflow is untouched.",
    "schedules.resume": "Let the schedule fire again.",
    "schedules.run": "Run the workflow once now, without waiting for the next time.",
    "schedules.remove": "Delete the cron job; the saved workflow stays.",
    "schedules.create": "Create or update the Hermes cron job for the chosen workflow.",
    "schedule.status": "Whether Hermes really has a cron job for this workflow, and when it next fires.",
    "runs.approve": "Answer this gate now; the run resumes from where it stopped.",
    "runs.resume": "Paste the agent step's result here and resume the run right where it paused.",
    "runs.agent": "Let the host agent produce this step's output now, then resume right where it paused.",
    "runs.retry": "Re-run this failed run from the step that failed; steps that already finished are kept.",
    "runs.open": "Open the saved workflow this run belongs to.",
    "runs.result": "Show this finished run's outputs in the run panel.",
    "runs.refresh": "Re-read the runs saved on this machine, newest first.",
  };

  // ---- friendly scheduler helpers (mirror visual_workflow_hermes/schedule.py) ----
  var PRESETS = ["daily", "weekdays", "weekly", "hourly", "custom"];
  var PRESET_LABELS = {
    daily: "Every day",
    weekdays: "Monday to Friday",
    weekly: "Once a week",
    hourly: "Every hour",
    custom: "Advanced (cron)",
  };
  var WEEKDAYS = [
    ["mon", "Monday"], ["tue", "Tuesday"], ["wed", "Wednesday"], ["thu", "Thursday"],
    ["fri", "Friday"], ["sat", "Saturday"], ["sun", "Sunday"],
  ];
  var DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var CRON_FIELDS = [
    ["minute", 0, 59], ["hour", 0, 23], ["day-of-month", 1, 31], ["month", 1, 12],
    ["day-of-week", 0, 7],
  ];

  function pad2(value) {
    return (value < 10 ? "0" : "") + value;
  }

  /** ``"09:30"`` -> ``[9, 30]``; null when it is not a 24h HH:MM. */
  function timeParts(value) {
    var m = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(String(value || "").trim());
    return m ? [parseInt(m[1], 10), parseInt(m[2], 10)] : null;
  }

  function weekdayIndex(name) {
    var key = String(name || "").slice(0, 3).toLowerCase();
    var i = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"].indexOf(key);
    return i < 0 ? 1 : i;
  }

  /** Preset picker values -> the cron expression that gets saved. */
  function buildCron(preset, time, weekday, custom) {
    if (preset === "custom") return String(custom || "").trim();
    var parts = timeParts(time);
    if (!parts) return "";
    var hour = parts[0];
    var minute = parts[1];
    if (preset === "hourly") return minute + " * * * *";
    if (preset === "daily") return minute + " " + hour + " * * *";
    if (preset === "weekdays") return minute + " " + hour + " * * 1-5";
    return minute + " " + hour + " * * " + weekdayIndex(weekday);
  }

  function cronFieldOk(raw, low, high) {
    var parts = String(raw).split(",");
    for (var i = 0; i < parts.length; i += 1) {
      var part = parts[i].trim();
      if (!part) return false;
      if (part.indexOf("/") >= 0) {
        var step = part.split("/");
        // Exactly one step segment: "*/15/2" and "5/10/extra" are not valid cron.
        if (step.length !== 2) return false;
        part = step[0];
        if (!/^\d+$/.test(step[1] || "") || parseInt(step[1], 10) < 1) return false;
        if (part !== "*" && part.indexOf("-") < 0 && !/^\d+$/.test(part)) return false;
      }
      if (part === "*") continue;
      if (part.indexOf("-") >= 0) {
        var span = part.split("-");
        if (!/^\d+$/.test(span[0] || "") || !/^\d+$/.test(span[1] || "")) return false;
        var from = parseInt(span[0], 10);
        var to = parseInt(span[1], 10);
        if (from > to || from < low || to > high) return false;
        continue;
      }
      if (!/^\d+$/.test(part)) return false;
      if (parseInt(part, 10) < low || parseInt(part, 10) > high) return false;
    }
    return true;
  }

  /** "" when the expression is a usable 5-field cron, else one line saying why not. */
  function cronProblem(expression) {
    var text = String(expression || "").trim();
    if (!text) return "enter a cron expression (5 fields, e.g. 0 9 * * 1-5)";
    var fields = text.split(/\s+/);
    if (fields.length !== 5) {
      return "cron needs 5 fields (minute hour day month weekday), got " + fields.length;
    }
    for (var i = 0; i < CRON_FIELDS.length; i += 1) {
      var spec = CRON_FIELDS[i];
      if (!cronFieldOk(fields[i], spec[1], spec[2])) {
        return spec[0] + " field " + fields[i] + " is not valid (allowed " + spec[1] + "-" +
          spec[2] + ", *, */n, a-b)";
      }
    }
    return "";
  }

  /** Plain words for a cron expression, so the canvas reads without decoding cron. */
  function describeCron(expression) {
    var text = String(expression || "").trim();
    if (cronProblem(text)) return text;
    var f = text.split(/\s+/);
    if (f[2] !== "*" || f[3] !== "*") return "custom schedule";
    if (f[1] === "*") {
      // "* * * * *" is valid cron (no fixed minute), so guard the cast or this reads ":NaN".
      return /^\d+$/.test(f[0]) ? "every hour at :" + pad2(parseInt(f[0], 10)) : "every hour";
    }
    if (!/^\d+$/.test(f[0]) || !/^\d+$/.test(f[1])) return "custom schedule";
    var at = pad2(parseInt(f[1], 10)) + ":" + pad2(parseInt(f[0], 10));
    if (f[4] === "*") return "every day at " + at;
    if (f[4] === "1-5") return "Monday to Friday at " + at;
    var name = DAY_NAMES[parseInt(f[4], 10) % 7];
    return /^\d+$/.test(f[4]) && name ? "every " + name + " at " + at : "custom schedule";
  }

  /** The preset a saved cron expression reads as; "custom" when it fits none. */
  function presetOf(expression) {
    var text = String(expression || "").trim();
    if (cronProblem(text)) return "custom";
    var f = text.split(/\s+/);
    if (f[2] !== "*" || f[3] !== "*") return "custom";
    if (f[1] === "*") return /^\d+$/.test(f[0]) ? "hourly" : "custom";
    if (!/^\d+$/.test(f[0]) || !/^\d+$/.test(f[1])) return "custom";
    if (f[4] === "1-5") return "weekdays";
    if (f[4] === "*") return "daily";
    // A list/step weekday has no weekly-picker equivalent; calling it weekly would coerce it.
    return /^\d+$/.test(f[4]) ? "weekly" : "custom";
  }

  function timeOf(expression) {
    var f = String(expression || "").trim().split(/\s+/);
    if (f.length === 5 && /^\d+$/.test(f[0]) && /^\d+$/.test(f[1])) {
      return pad2(parseInt(f[1], 10)) + ":" + pad2(parseInt(f[0], 10));
    }
    return "09:00";
  }

  function weekdayOf(expression) {
    var f = String(expression || "").trim().split(/\s+/);
    if (f.length === 5 && /^\d+$/.test(f[4])) {
      // cron day-of-week is 0=Sunday..6=Saturday (7 is Sunday too); WEEKDAYS starts at Monday.
      var dayName = DAY_NAMES[parseInt(f[4], 10) % 7];
      for (var i = 0; i < WEEKDAYS.length; i += 1) {
        if (WEEKDAYS[i][1] === dayName) return WEEKDAYS[i][0];
      }
    }
    return "mon";
  }
  // Compact cards: the canvas is often 600px wide inside a dashboard that already has two
  // sidebars open, so a node is 150x58 and its preview is at most two short lines.
  var NODE_W = 150;
  var NODE_H = 58;
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
    // JSON, not "from>to": an id may itself contain '>', and the key is parsed back when a
    // selected edge is deleted. JSON keeps the pair unambiguous without a charset rule.
    return JSON.stringify([from, to]);
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
    ".vw-shell{--vw-ink:var(--midground,#ffe6cb);--vw-dim:color-mix(in srgb,var(--midground,#ffe6cb) 72%,transparent);--vw-surface:color-mix(in srgb,var(--midground,#ffe6cb) 5%,var(--background,#041c1c));--vw-line:color-mix(in srgb,var(--midground,#ffe6cb) 16%,transparent);--vw-node:color-mix(in srgb,var(--midground,#ffe6cb) 7%,var(--background,#041c1c));--vw-note-yellow:color-mix(in srgb,#f2d16b 20%,var(--background,#041c1c));--vw-note-blue:color-mix(in srgb,#6ea8fe 20%,var(--background,#041c1c));--vw-note-green:color-mix(in srgb,#34d399 20%,var(--background,#041c1c));--vw-note-red:color-mix(in srgb,#fb2c36 20%,var(--background,#041c1c));--vw-accent:var(--series-output-token,#34d399);--vw-danger:#fb2c36;display:flex;flex-direction:column;min-height:0;min-width:0;font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--vw-ink);text-align:left}",
    ".vw-rail-title{margin:0 0 6px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--vw-dim)}",
    ".vw-list{display:flex;flex-direction:column;gap:4px;margin:0 0 10px}",
    ".vw-top{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:6px 8px;border-bottom:1px solid var(--vw-line);background:var(--vw-surface)}",
    ".vw-top .vw-grow{flex:1 1 160px;min-width:120px}",
    ".vw-stage{flex:1 1 auto;min-width:0;display:flex;flex-direction:column}",
    // flex:0 0 auto keeps the app content-sized. As a growing item it inherited whatever height
    // the host wrapper guessed at load (1010px here, far past the window) and then collapsed to
    // 458px the moment a node was selected — the canvas lost half its band and the run box fell
    // below the fold. A fixed basis makes the surface identical before and after a selection.
    ".vw-app{display:flex;flex-direction:column;flex:0 0 auto;min-width:0;padding:6px 8px}",
    // flex:0 0 auto is deliberate: the kit is a fixed row, not a spacer. As a growing flex
    // item in the column shell it stretched to fill the height the canvas gave up when a node
    // was selected, which drew a band of nothing between the node bar and the name row.
    ".vw-kit{display:flex;gap:4px;align-items:center;overflow-x:auto;flex:0 0 auto;min-width:0;padding:0 0 6px;border-bottom:1px solid var(--vw-line)}",
    ".vw-tool{display:inline-flex;align-items:center;gap:5px;flex:0 0 auto;white-space:nowrap;cursor:grab}",
    ".vw-tool .ico{font-size:12px;line-height:1}",
    ".vw-kit-hint{flex:0 1 auto;margin:0 0 0 auto;padding-left:8px;font-size:11px;color:var(--vw-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    ".vw-bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:6px 0;border-bottom:1px solid var(--vw-line)}",
    ".vw-bar .vw-grow{flex:1 1 140px;min-width:100px}",
    ".vw-main{display:flex;flex:1 1 auto;min-width:0;min-height:0}",
    // The canvas asks for its own band instead of inheriting whatever the host left over, so
    // opening the inspector can never take the drawing surface away.
    ".vw-wrap{flex:1 1 auto;min-width:0;min-height:clamp(320px,calc(100dvh - 240px),900px);overflow:auto;padding:6px}",
    ".vw-inspector{flex:0 0 auto;width:252px;box-sizing:border-box;padding:4px 0 8px 10px;border-left:1px solid var(--vw-line);overflow:auto}",
    ".vw-insp-toggle{font:inherit;color:var(--vw-dim);background:none;border:0;padding:2px 4px;cursor:pointer;text-align:left}",
    ".vw-insp-toggle:hover{color:var(--vw-ink)}",
    ".vw-app.vw-insp-collapsed .vw-inspector{width:30px;padding:4px 2px;overflow:hidden}",
    ".vw-app.vw-insp-collapsed .vw-insp-body{display:none}",
    // No height:100% here. A percentage height inside an auto-height row is a cyclic dependency,
    // and Chrome settled it at 911px — which is what made the canvas band 911px tall before a
    // selection and 458px after it.
    ".vw-app.vw-insp-collapsed .vw-insp-toggle{writing-mode:vertical-rl;font-size:10px;letter-spacing:.08em;text-transform:uppercase;padding-top:4px}",
    ".vw-errors,.vw-run{margin:0;padding:6px 0;border-top:1px solid var(--vw-line);white-space:pre-wrap;color:var(--vw-dim);max-height:150px;overflow:auto}",
    // A run's outcome must never be a transient word in the bar. This banner sits directly
    // above the canvas, stays until dismissed or replaced, and is announced to screen readers.
    ".vw-banner{display:flex;gap:8px;align-items:flex-start;margin:6px 0 0;padding:6px 8px;border:1px solid var(--vw-line);border-left:3px solid var(--vw-accent);background:var(--vw-surface);color:var(--vw-ink);white-space:pre-wrap;max-height:140px;overflow:auto}",
    ".vw-banner[hidden]{display:none}",
    ".vw-banner-warn{border-left-color:var(--vw-note-yellow)}",
    ".vw-banner-error{border-left-color:var(--vw-danger);color:var(--vw-danger)}",
    ".vw-banner p{margin:0;flex:1 1 auto;min-width:0}",
    ".vw-banner .vw-pill{flex:0 0 auto;padding:0 6px}",
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
    // The diagnosed-failure chip next to a failed run's error text; the hint rides the title.
    ".vw-chip{display:inline-block;margin-left:6px;padding:0 8px;border-radius:9px;font-size:11px;line-height:18px;border:1px solid var(--vw-line);background:var(--vw-node);color:var(--vw-dim)}",
    ".vw-canvas{display:block}",
    ".vw-canvas g.vw-node{cursor:grab}",
    ".vw-canvas g.vw-node:active{cursor:grabbing}",
    ".vw-port{fill:var(--vw-surface);stroke:var(--vw-line);stroke-width:1.5;cursor:crosshair}",
    ".vw-port:hover{fill:var(--vw-accent);stroke:var(--vw-accent)}",
    ".vw-edge{fill:none;stroke:var(--vw-line);stroke-width:1.6}",
    ".vw-edge-on{stroke:var(--vw-accent);stroke-width:2.4}",
    ".vw-edge-hit{fill:none;stroke:transparent;stroke-width:12;cursor:pointer}",
    ".vw-ghost{fill:none;stroke:var(--vw-accent);stroke-width:1.6;stroke-dasharray:4 3}",
    ".vw-views{display:flex;gap:4px;margin:0}",
    ".vw-stage-sched{display:block;overflow:auto;padding:8px 10px}",
    ".vw-job{padding:6px 0;border-bottom:1px solid var(--vw-line)}",
    ".vw-job-head{display:flex;gap:4px;align-items:baseline}",
    ".vw-job-actions{display:flex;gap:4px;margin-top:4px}",
    ".vw-sched-form{display:flex;flex-direction:column;gap:2px;max-width:320px;margin-top:10px}",
  ].join("\n");

  var TEMPLATE =
    '<div class="vw-app vw-insp-collapsed">' +
    '  <div class="vw-kit">' +
    '    <button class="vw-pill vw-tool" type="button" draggable="true" data-kind="trigger"><span class="ico">\u25b6</span>Trigger</button>' +
    '    <button class="vw-pill vw-tool" type="button" draggable="true" data-kind="agent"><span class="ico">\u2726</span>Agent</button>' +
    '    <button class="vw-pill vw-tool" type="button" draggable="true" data-kind="condition"><span class="ico">\u25c7</span>Condition</button>' +
    '    <button class="vw-pill vw-tool" type="button" draggable="true" data-kind="approval"><span class="ico">\u2713</span>Approval</button>' +
    '    <button class="vw-pill vw-tool" type="button" draggable="true" data-kind="output"><span class="ico">\u25a4</span>Output</button>' +
    '    <button class="vw-pill vw-tool" type="button" draggable="true" data-kind="note"><span class="ico">\u270e</span>Note</button>' +
    '    <p class="vw-kit-hint">Click a node to add it, or drag it onto the canvas. Drag a node&rsquo;s right port to another node&rsquo;s left port.</p>' +
    '  </div>' +
    '  <div class="vw-bar">' +
    '    <input class="vw-grow" data-vw="name" type="text" value="untitled" aria-label="design name">' +
    '    <button class="vw-pill" type="button" data-vw="validate">Validate</button>' +
    '    <button class="vw-pill" type="button" data-vw="save">Save</button>' +
    '    <button class="vw-pill" type="button" data-vw="run-now">Run</button>' +
    '    <button class="vw-pill" type="button" data-vw="delete">Delete</button>' +
    '    <span class="vw-muted" data-vw="status"></span>' +
    '  </div>' +
    '  <div class="vw-banner" data-vw="banner" role="status" aria-live="polite" aria-atomic="true" hidden></div>' +
    '  <div class="vw-main">' +
    '    <div class="vw-wrap" data-vw="wrap">' +
    '      <svg class="vw-canvas" data-vw="canvas" role="img" aria-label="workflow canvas"></svg>' +
    '    </div>' +
    '    <div class="vw-inspector">' +
    '      <button class="vw-insp-toggle" type="button" data-vw="insp-toggle" aria-expanded="false" aria-controls="vw-insp-body">Inspector</button>' +
    '      <div class="vw-insp-body" id="vw-insp-body" data-vw="inspector"></div>' +
    '    </div>' +
    '  </div>' +
    '  <div class="vw-run" data-vw="run"></div>' +
    '  <pre class="vw-errors" data-vw="errors" hidden></pre>' +
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
      app: q(".vw-app"),
      toggle: q('[data-vw="insp-toggle"]'),
      name: q('[data-vw="name"]'),
      canvas: q('[data-vw="canvas"]'),
      wrap: q('[data-vw="wrap"]'),
      inspector: q('[data-vw="inspector"]'),
      errors: q('[data-vw="errors"]'),
      status: q('[data-vw="status"]'),
      banner: q('[data-vw="banner"]'),
      run: q('[data-vw="run"]'),
    };

    var graph = clone(BLANK);
    var selected = null;
    var selectedEdge = null;
    var linkArm = null;   // source node id after a click on an output port
    var dragLink = null;  // live drag from an output port: {from, x1, y1, x2, y2}
    var lastRun = null;
    // Latest mounted run's outputs by node id, painted under their nodes by draw().
    // Kept with the run's design name so switching designs never paints stale text.
    var lastOutputs = {};
    var lastRunName = "";
    var savedNames = [];   // names known to exist server-side; Run refuses a draft instead of 404ing
    var designsLoaded = false;  // only gate Run once GET /designs actually succeeded
    var sizeObserver = null;    // kept so unmount can disconnect it
    var gestureCleanup = null;  // cancels an in-flight drag/link on unmount or window blur

    function nodeById(id) {
      var hits = graph.nodes.filter(function (n) {
        return n.id === id;
      });
      return hits[0] || null;
    }

    function layout() {
      graph.nodes.forEach(function (n, i) {
        if (typeof n.x !== "number" || typeof n.y !== "number") {
          n.x = 26 + (i % 4) * 172;
          n.y = 28 + Math.floor(i / 4) * 92;
        }
      });
    }

    /** Notes carry one of a fixed set of tints; anything else reads as the default yellow. */
    function noteColor(n) {
      var name = String(n.color || "").toLowerCase();
      return NOTE_COLORS.indexOf(name) >= 0 ? name : "yellow";
    }

    /** At most two short lines of a node's own text, cut on a word where there is one. */
    function previewLines(n) {
      var text =
        n.type === "note" ? n.text || "" :
        n.type === "agent" ? n.prompt || "" :
        n.type === "condition" ? n.expression || "" :
        n.type === "approval" ? n.question || "" :
        n.type === "trigger" ? (n.trigger_mode || "") + (n.schedule ? " " + n.schedule : "") :
        (n.after || []).join(", ");
      text = String(text).replace(/\s+/g, " ").trim();
      var lines = [];
      while (text && lines.length < 2) {
        if (text.length <= 22) {
          lines.push(text);
          break;
        }
        var cut = text.lastIndexOf(" ", 22);
        if (cut < 8) cut = 22;
        lines.push(text.slice(0, cut).trim());
        text = text.slice(cut).trim();
      }
      if (text && lines.length === 2) { lines[1] = lines[1].slice(0, 21) + "\u2026"; }
      return lines;
    }

    /** One node's last-run output as short canvas lines: strings verbatim, anything
     *  else as JSON, capped before wrapping so a digest cannot bury the canvas.
     *  Slicing is code-point based so emoji never splits into tofu. */
    function summarizeOutputs(result) {
      var out = {};
      var outputs = (result && result.outputs) || {};
      Object.keys(outputs).forEach(function (id) {
        var text = outputs[id];
        text = typeof text === "string" ? text : JSON.stringify(text);
        text = String(text == null ? "" : text).replace(/\s+/g, " ").trim();
        var chars = Array.from(text);
        if (chars.length > 140) { text = chars.slice(0, 139).join("") + "\u2026"; }
        if (text) { out[id] = text; }
      });
      return out;
    }

    /** Wrapped excerpt of one node's last output, or [] when there is nothing to show
     *  (no run yet, or the mounted run belongs to another design). */
    function outputLines(id) {
      if (!lastRunName || lastRunName !== graph.name) { return []; }
      var rest = lastOutputs[id] || "";
      if (!rest) { return []; }
      var lines = [];
      var chars = Array.from(rest);
      while (chars.length && lines.length < 2) {
        if (chars.length <= 22) { lines.push(chars.join("")); break; }
        var cut = chars.lastIndexOf(" ", 22);
        if (cut < 8) { cut = 22; }
        lines.push(chars.slice(0, cut).join("").trim());
        chars = chars.slice(cut);
        while (chars.length && chars[0] === " ") { chars.shift(); }
      }
      if (chars.length && lines.length === 2) {
        lines[1] = Array.from(lines[1]).slice(0, 21).join("") + "\u2026";
      }
      return lines;
    }

    /** Collapsed to a 30px strip by default; a selection opens it, the toggle closes it. */
    function setInspector(open) {
      el.app.classList.toggle("vw-insp-collapsed", !open);
      el.toggle.setAttribute("aria-expanded", open ? "true" : "false");
      el.toggle.textContent = open ? "Inspector \u00bb" : "Inspector";
    }

    /**
     * Fit the drawing to the wrapper's width, never above 1:1 (so text stays crisp).
     *
     * The SVG is a fixed virtual sheet whose viewBox is the graph's bounds; the rendered width
     * is the wrapper's, so a narrow tab scales the whole graph down instead of clipping it.
     * Only width is measured: height follows the aspect ratio and the wrapper scrolls.
     */
    var fitLocked = false;

    function fit() {
      var svg = el.canvas;
      var avail = Math.max(240, (el.wrap.clientWidth || 0) - 12);
      var maxX = 0;
      var maxY = 0;
      graph.nodes.forEach(function (n) {
        maxX = Math.max(maxX, n.x + NODE_W);
        maxY = Math.max(maxY, n.y + NODE_H);
      });
      var width = Math.max(maxX + 30, 320);
      var height = Math.max(maxY + 30, 200);
      var scale = avail / width;
      if (scale > 1) {
        width = avail;
        scale = 1;
      }
      svg.setAttribute("viewBox", "0 0 " + Math.round(width) + " " + Math.round(height));
      svg.setAttribute("width", Math.round(avail));
      svg.setAttribute("height", Math.round(Math.max(200, height * scale)));
      svg.setAttribute("preserveAspectRatio", "xMinYMin meet");
    }

    /** Re-fit when the tab itself is resized (sidebars opening, window drag). */
    function watchSize() {
      if (typeof ResizeObserver !== "function") return;
      var width = el.wrap.clientWidth;
      sizeObserver = new ResizeObserver(function () {
        // A detached wrap is not a resize: stop fitting a canvas nobody can see.
        if (!el.wrap.isConnected) return;
        if (el.wrap.clientWidth !== width) {
          width = el.wrap.clientWidth;
          fit();
        }
      });
      sizeObserver.observe(el.wrap);
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
        var g = svgEl("g", {
          transform: "translate(" + n.x + "," + n.y + ")",
          "class": "vw-node",
          "data-id": n.id,
        });
        // SVG tooltips are a child <title>, not a title attribute.
        var tip = svgEl("title", {});
        tip.textContent = n.id + " \u00b7 " + (TIPS[n.type] || n.type);
        g.appendChild(tip);
        var isNote = n.type === NOTE;
        var box = {
          width: NODE_W, height: NODE_H, rx: 6,
          fill: isNote ? "var(--vw-note-" + noteColor(n) + ")" : "var(--vw-node)",
          stroke: isSelected ? "var(--vw-accent)" : "var(--vw-line)",
          "stroke-width": isSelected ? 2 : 1,
        };
        // A dashed edge is the cheapest "this is paper, not a step" cue that survives theming.
        if (isNote) box["stroke-dasharray"] = "5 3";
        g.appendChild(svgEl("rect", box));
        var kind = svgEl("text", { x: 9, y: 13, "font-size": 8, fill: "var(--vw-dim)" });
        kind.textContent = String(n.type).toUpperCase();
        var id = svgEl("text", { x: 9, y: 26, "font-size": 11, fill: "var(--vw-ink)" });
        id.textContent = n.id;
        g.appendChild(kind);
        g.appendChild(id);
        previewLines(n).forEach(function (text, line) {
          var row = svgEl("text", {
            x: 9, y: 38 + line * 11, "font-size": 9, fill: "var(--vw-dim)",
          });
          row.textContent = text;
          g.appendChild(row);
        });
        outputLines(n.id).forEach(function (text, line) {
          var out = svgEl("text", {
            x: 9, y: NODE_H + 12 + line * 11, "font-size": 9, fill: "var(--vw-dim)",
            class: "vw-output",
          });
          out.textContent = text;
          g.appendChild(out);
        });

        // A note has no ports at all: it takes no part in the graph, so there is nothing to
        // drag from and nothing to drop onto.
        if (n.type !== NOTE) {
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
        }

        wireNode(g, n);
        svg.appendChild(g);
      });
      if (!fitLocked) fit();
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
        fitLocked = true;
        var start = svgPoint(ev);
        var offset = { x: start.x - n.x, y: start.y - n.y };
        var moved = false;
        var frame = null;
        // One redraw per animation frame, not one per pixel: draw() rebuilds the whole SVG.
        function scheduleDraw() {
          if (frame) return;
          if (typeof requestAnimationFrame !== "function") { draw(); return; }
          frame = requestAnimationFrame(function () { frame = null; draw(); });
        }
        function cleanup() {
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
          document.removeEventListener("pointercancel", cancel);
          window.removeEventListener("blur", cancel);
          if (frame && typeof cancelAnimationFrame === "function") cancelAnimationFrame(frame);
          frame = null;
          gestureCleanup = null;
        }
        // Released off-window / cancelled: never leave fitLocked stuck or a ghost on screen.
        function cancel() {
          cleanup();
          fitLocked = false;
          draw();
        }
        function onMove(moveEv) {
          var p = svgPoint(moveEv);
          if (Math.abs(p.x - start.x) > 3 || Math.abs(p.y - start.y) > 3) moved = true;
          n.x = Math.max(0, Math.round(p.x - offset.x));
          n.y = Math.max(0, Math.round(p.y - offset.y));
          scheduleDraw();
        }
        function onUp() {
          cleanup();
          fitLocked = false;
          if (!moved) pick(n.id);
          else draw();
        }
        gestureCleanup = cancel;
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
        document.addEventListener("pointercancel", cancel);
        window.addEventListener("blur", cancel);
      });
    }

    function pick(id) {
      selected = id;
      selectedEdge = null;
      setInspector(true);
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
      fitLocked = true;
      dragLink = { from: n.id, x1: origin.x, y1: origin.y, x2: start.x, y2: start.y };
      draw();
      var frame = null;
      function scheduleDraw() {
        if (frame) return;
        if (typeof requestAnimationFrame !== "function") { draw(); return; }
        frame = requestAnimationFrame(function () { frame = null; draw(); });
      }
      function cleanup() {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.removeEventListener("pointercancel", cancel);
        window.removeEventListener("blur", cancel);
        if (frame && typeof cancelAnimationFrame === "function") cancelAnimationFrame(frame);
        frame = null;
        gestureCleanup = null;
      }
      function cancel() {
        cleanup();
        dragLink = null;
        fitLocked = false;
        draw();
      }
      function onMove(moveEv) {
        var p = svgPoint(moveEv);
        if (Math.abs(p.x - start.x) > 3 || Math.abs(p.y - start.y) > 3) moved = true;
        dragLink.x2 = p.x;
        dragLink.y2 = p.y;
        scheduleDraw();
      }
      function onUp(upEv) {
        cleanup();
        var from = dragLink.from;
        dragLink = null;
        fitLocked = false;
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
    gestureCleanup = cancel;
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    document.addEventListener("pointercancel", cancel);
    window.addEventListener("blur", cancel);
  }

    /** Add the *from* -> *to* edge, refusing the three ways it could be wrong. */
    function finishLink(from, to) {
      linkArm = null;
      var source = nodeById(from);
      var target = nodeById(to);
      if (!source || !target) return;
      if (source.type === NOTE || target.type === NOTE) {
        note("a note cannot hold a workflow step");
      } else if (target.type === "trigger") {
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

    function removeSelected() {
      if (selectedEdge) {
        var pair = JSON.parse(selectedEdge);
        cutEdge(pair[0], pair[1]);
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
      linkArm = null;
      buildInspector();
      draw();
      note("removed " + removed);
    }

  /** A labelled inspector row. The tip rides on the label AND the control, so hovering
   *  either one explains it (a native title is the whole mechanism, here and in SVG). */
  function field(labelText, control, tip) {
    var wrap = document.createElement("div");
    var label = document.createElement("div");
    label.className = "vw-label";
    label.textContent = labelText;
    if (tip) {
      label.title = tip;
      control.title = tip;
    }
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
    var models = options.models || [];
    // Slug of the host's active provider ("" when unknown): only its models can
    // actually run, so the picker offers those. Set alongside the catalog.
    var currentProvider = "";

    function profileByName(name) {
      if (!name) return null;
      var hits = profiles.filter(function (p) {
        return p.name === name;
      });
      return hits[0] || null;
    }

    function profileSelect(current) {
      var select = document.createElement("select");
      select.title = TIPS["agent.profile"];
      var blank = document.createElement("option");
      blank.value = "";
      blank.textContent = profiles.length ? "\u2014 host default \u2014" : "\u2014 no profiles listed \u2014";
      blank.title = TIPS["agent.profile"];
      select.appendChild(blank);
      var known = false;
      profiles.forEach(function (p) {
        var option = document.createElement("option");
        option.value = p.name;
        option.textContent = p.label && p.label !== p.name ? p.label + " (" + p.name + ")" : p.name;
        option.title = TIPS["agent.profile"];
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

    /** The host catalog as a grouped <select>: one optgroup per provider, because a step names
     *  exactly one model and the runtime derives its provider. Only the active provider's
     *  models are offered — anything else would fail loudly server-side. With no catalog,
     *  or an unknown active provider, the field stays typeable (fail open, never empty),
     *  and a saved model the catalog dropped stays selectable. */
    function modelSelect(current) {
      if (!models.length) {
        return textInput(current.model || "", function (v) {
          if (v) current.model = v;
          else delete current.model;
        }, "model id (optional)");
      }
      var offered = currentProvider
        ? models.filter(function (p) { return p.slug === currentProvider; })
        : models;
      if (!offered.length) { offered = models; }
      var select = document.createElement("select");
      select.title = TIPS["agent.model"];
      var blank = document.createElement("option");
      blank.value = "";
      blank.textContent = "\u2014 the bot's own model \u2014";
      blank.title = TIPS["agent.model"];
      select.appendChild(blank);
      var known = false;
      offered.forEach(function (p) {
        var group = document.createElement("optgroup");
        group.label = p.label || p.slug;
        (p.models || []).forEach(function (id) {
          var option = document.createElement("option");
          option.value = id;
          option.textContent = id;
          option.title = TIPS["agent.model"];
          if (id === current.model) {
            option.selected = true;
            known = true;
          }
          group.appendChild(option);
        });
        if (group.children.length) select.appendChild(group);
      });
      if (current.model && !known) {
        // A saved design can name a model this host no longer lists: keep it visible so
        // opening the inspector cannot silently retarget the step.
        var stale = document.createElement("option");
        stale.value = current.model;
        stale.textContent = current.model + " (not listed)";
        stale.selected = true;
        select.appendChild(stale);
      }
      select.addEventListener("change", function () {
        if (select.value) current.model = select.value;
        else delete current.model;
        draw();
      });
      return select;
    }

    /** Chats the host gateway has seen (``GET /channels``); empty means the canvas offers a
     *  free-text field instead of a picker that cannot fill. */
    var channels = options.channels || [];

    /** One send-to value -> the two fields the backend reads. A bare platform is that
     *  platform's home channel (a notification); anything with a colon is one specific chat.
     *  Deriving both from one value is what makes the invalid pair impossible to build. */
    function applySendTo(node, value) {
      var target = String(value || "").trim();
      delete node.deliver;
      delete node.target;
      if (!target) return node;
      node.deliver = target.indexOf(":") === -1 ? "notification" : "channel";
      node.target = target;
      return node;
    }

    /** The picker value a saved node shows: no delivery mode = collect only. */
    function sendToValue(node) {
      return node.deliver ? String(node.target || "") : "";
    }

    function sendToSelect(current) {
      var select = document.createElement("select");
      var blank = document.createElement("option");
      blank.value = "";
      blank.textContent = "collect only \u2014 do not send";
      blank.title = TIPS["output.send_to"];
      select.appendChild(blank);
      var value = sendToValue(current);
      var known = false;
      channels.forEach(function (item) {
        var option = document.createElement("option");
        option.value = item.id;
        option.textContent = item.label || item.id;
        option.title = item.id;
        if (item.id === value) {
          option.selected = true;
          known = true;
        }
        select.appendChild(option);
      });
      if (value && !known) {
        // A saved target the gateway has not listed must stay visible, not reset.
        var stale = document.createElement("option");
        stale.value = value;
        stale.textContent = value + " (not listed)";
        stale.title = TIPS["output.target"];
        stale.selected = true;
        select.appendChild(stale);
      }
      select.addEventListener("change", function () {
        applySendTo(current, select.value);
        buildInspector();
        draw();
      });
      return select;
    }

    /** The friendly scheduler: a preset picker, the time or day it needs, and the cron it
     *  produces. ``node.schedule`` stays the single source of truth, so the saved design and
     *  the cron job the backend creates cannot disagree. */
    function scheduleFields(node) {
      var wrap = document.createElement("div");
      var preset = presetOf(node.schedule);
      var reading = document.createElement("p");

      var picker = document.createElement("select");
      PRESETS.forEach(function (name) {
        var option = document.createElement("option");
        option.value = name;
        option.textContent = PRESET_LABELS[name];
        option.title = TIPS["presets." + name];
        if (name === preset) option.selected = true;
        picker.appendChild(option);
      });
      picker.addEventListener("change", function () {
        if (picker.value !== "custom") {
          node.schedule = buildCron(picker.value, timeOf(node.schedule), weekdayOf(node.schedule));
        }
        buildInspector();
        draw();
      });
      wrap.appendChild(field("runs", picker, TIPS["trigger.preset"]));

      if (preset === "weekly") {
        var day = document.createElement("select");
        WEEKDAYS.forEach(function (pair) {
          var option = document.createElement("option");
          option.value = pair[0];
          option.textContent = pair[1];
          option.title = TIPS["trigger.weekday"];
          if (pair[0] === weekdayOf(node.schedule)) option.selected = true;
          day.appendChild(option);
        });
        day.addEventListener("change", function () {
          node.schedule = buildCron(preset, timeOf(node.schedule), day.value);
          buildInspector();
          draw();
        });
        wrap.appendChild(field("day", day, TIPS["trigger.weekday"]));
      }

      // Shown for hourly too: buildCron takes the MINUTE from it, so hiding the field
      // silently pinned "every hour" to :00 with no way to choose :15.
      if (preset !== "custom") {
        var time = textInput(timeOf(node.schedule), function (v) {
          if (!timeParts(v)) {
            reading.className = "vw-error";
            reading.textContent = "time must be HH:MM (24h), e.g. 09:30";
            return;
          }
          node.schedule = buildCron(preset, v, weekdayOf(node.schedule));
          draw();
          reading.className = "vw-hint";
          reading.textContent = describeCron(node.schedule);
        }, "09:00");
        wrap.appendChild(field("time (24h)", time, TIPS["trigger.time"]));
      }

      var cron = textInput(node.schedule || "", function (v) {
        node.schedule = v;
        draw();
        var problem = cronProblem(v);
        reading.className = problem ? "vw-error" : "vw-hint";
        reading.textContent = problem || describeCron(v);
      }, "0 9 * * 1-5");
      wrap.appendChild(field("cron (advanced)", cron, TIPS["trigger.schedule"]));

      var problem = cronProblem(node.schedule);
      reading.className = problem ? "vw-error" : "vw-hint";
      reading.textContent = problem || describeCron(node.schedule);
      reading.title = TIPS["trigger.schedule"];
      wrap.appendChild(reading);

      // The canvas can edit a cron expression without Hermes knowing about it. Say which is
      // true: the job that exists on the host, or that nothing is scheduled yet.
      var statusLine = document.createElement("p");
      statusLine.className = "vw-hint";
      statusLine.title = TIPS["schedule.status"];
      statusLine.textContent = "Hermes cron: checking\u2026";
      wrap.appendChild(statusLine);
      function jobStatus() {
        var owner = currentName();
        if (!owner) {
          statusLine.className = "vw-hint";
          statusLine.textContent = "Hermes cron: save the workflow, then schedule it.";
          return;
        }
        call(API + "/schedules").then(function (data) {
          var jobs = (data && data.jobs) || [];
          var job = null;
          jobs.forEach(function (candidate) {
            if ((candidate.design || "") === owner) job = candidate;
          });
          statusLine.className = "vw-hint";
          if (!data || !data.available) {
            statusLine.textContent = "Hermes cron: the scheduler could not be read here.";
          } else if (job) {
            statusLine.textContent = "Hermes cron: " + job.state +
              (job.next_run_at ? " \u00b7 next " + job.next_run_at : "") +
              "  (" + job.schedule + ")";
          } else {
            statusLine.textContent =
              "Hermes cron: not scheduled yet \u2014 press Schedule in Hermes.";
          }
        }).catch(function () {
          statusLine.textContent = "Hermes cron: could not be read.";
        });
      }
      jobStatus();

      var apply = button("Schedule in Hermes", function () {
        var name = currentName();
        if (!name) {
          reading.className = "vw-error";
          reading.textContent = "save the workflow first, then schedule it";
          return;
        }
        var issue = cronProblem(node.schedule);
        if (issue) {
          reading.className = "vw-error";
          reading.textContent = issue;
          return;
        }
        reading.className = "vw-hint";
        reading.textContent = "scheduling\u2026";
        call(path(name) + "/schedule", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          // Same shape as the Schedules form, so the two call sites cannot drift.
          body: JSON.stringify({
            preset: presetOf(node.schedule),
            time: timeOf(node.schedule),
            weekday: weekdayOf(node.schedule),
            cron: node.schedule,
          }),
        }).then(function (data) {
          if (!data.ok) {
            reading.className = "vw-error";
            reading.textContent = data.error || "the scheduler refused it";
            return;
          }
          reading.className = "vw-hint";
          reading.textContent = (data.created ? "scheduled \u00b7 " : "updated \u00b7 ") +
            describeCron(data.cron || node.schedule);
          onSaved();
          jobStatus();
        }).catch(function (err) {
          reading.className = "vw-error";
          reading.textContent = explain(err);
        });
      });
      apply.title = TIPS["schedule.save"];
      wrap.appendChild(apply);
      return wrap;
    }

    function buildInspector() {
      var box = el.inspector;
      box.textContent = "";
      var current = selected ? nodeById(selected) : null;
      if (!current) {
        setInspector(false);
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

      if (current.type === NOTE) {
        box.appendChild(field("note text", textArea(current.text || "", function (v) {
          current.text = v;
          draw();
        }, 3), TIPS["note.text"]));
        var tint = document.createElement("select");
        tint.title = TIPS["note.color"];
        NOTE_COLORS.forEach(function (name) {
          var option = document.createElement("option");
          option.value = name;
          option.textContent = name;
          option.title = TIPS["note.color"];
          if (noteColor(current) === name) option.selected = true;
          tint.appendChild(option);
        });
        tint.addEventListener("change", function () {
          current.color = tint.value;
          draw();
        });
        box.appendChild(field("colour", tint, TIPS["note.color"]));
        // Say the one thing a note is easy to be mistaken for: a step.
        var why = document.createElement("p");
        why.className = "vw-hint";
        why.title = TIPS["note"];
        why.textContent = "A note is for people reading the canvas; it never runs.";
        box.appendChild(why);
      } else if (current.type === "trigger") {
        var select = document.createElement("select");
        select.title = TIPS["trigger.trigger_mode"];
        MODES.forEach(function (mode) {
          var option = document.createElement("option");
          option.value = mode;
          option.textContent = mode;
          option.title = TIPS["trigger.trigger_mode"];
          if (current.trigger_mode === mode) option.selected = true;
          select.appendChild(option);
        });
        select.addEventListener("change", function () {
          current.trigger_mode = select.value;
          buildInspector();
          draw();
        });
        box.appendChild(field("trigger_mode", select, TIPS["trigger.trigger_mode"]));
        if (current.trigger_mode === "schedule") {
          box.appendChild(scheduleFields(current));
        }
      } else if (current.type === "agent") {
        box.appendChild(field("prompt", textArea(current.prompt || "", function (v) {
          current.prompt = v;
          draw();
        }, 5), TIPS["agent.prompt"]));
        box.appendChild(field("profile / bot (optional)", profileSelect(current), TIPS["agent.profile"]));
        var chosen = profileByName(current.profile);
        if (chosen) {
          var runs = document.createElement("p");
          runs.className = "vw-hint";
        runs.textContent = "runs as " + (chosen.label || chosen.name) +
          (chosen.model ? " \u00b7 " + chosen.model : "");
          box.appendChild(runs);
        }
        box.appendChild(field("model (optional)", modelSelect(current), TIPS["agent.model"]));
        box.appendChild(field("retries (optional)", textInput(
          current.retries ? String(current.retries) : "",
          function (v) {
            var count = parseInt(v, 10);
            if (!v.trim() || isNaN(count) || count <= 0) delete current.retries;
            else current.retries = Math.min(3, count);
            draw();
          },
          "0"
        ), TIPS["agent.retries"]));
      } else if (current.type === "condition") {
        box.appendChild(field("expression", textInput(current.expression || "", function (v) {
          current.expression = v;
          draw();
        }, "out.draft.word_count > 20"), TIPS["condition.expression"]));
        var hint = document.createElement("p");
        hint.className = "vw-hint";
        hint.textContent = "Must start with out.<node>.<field> <op> <value>.";
        box.appendChild(hint);
      } else if (current.type === "approval") {
        box.appendChild(field("question", textArea(current.question || "", function (v) {
          current.question = v;
          draw();
        }, 3), TIPS["approval.question"]));
        box.appendChild(field("context (optional)", textArea(current.context || "", function (v) {
          if (v.trim()) current.context = v;
          else delete current.context;
          draw();
        }, 3), TIPS["approval.context"]));
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
        ), TIPS["approval.options"]));
        box.appendChild(field("timeout (minutes, optional)", textInput(
          current.timeout_minutes ? String(current.timeout_minutes) : "",
          function (v) {
            var minutes = parseInt(v, 10);
            if (!v.trim() || isNaN(minutes) || minutes <= 0) delete current.timeout_minutes;
            else current.timeout_minutes = minutes;
            draw();
          },
          "60"
        ), TIPS["approval.timeout"]));
        var policy = document.createElement("select");
        policy.title = TIPS["approval.on_timeout"];
        [["reject", "reject \u2014 fail the run"],
         ["escalate", "escalate \u2014 flag it for someone else"]].forEach(function (pair) {
          var option = document.createElement("option");
          option.value = pair[0];
          option.textContent = pair[1];
          option.title = TIPS["approval.on_timeout"];
          if ((current.on_timeout || "reject") === pair[0]) option.selected = true;
          policy.appendChild(option);
        });
        policy.addEventListener("change", function () {
          current.on_timeout = policy.value;
          draw();
        });
        box.appendChild(field("if it times out", policy, TIPS["approval.on_timeout"]));
      } else if (current.type === "output") {
        var parents = document.createElement("p");
        parents.className = "vw-muted";
        parents.textContent = (current.after || []).length
          ? (current.after || []).join(", ")
          : "(no parents \u2014 this output collects nothing)";
        box.appendChild(field("parents", parents, TIPS["output.parents"]));
        if (channels.length) {
          box.appendChild(field("send to", sendToSelect(current), TIPS["output.send_to"]));
        } else {
          box.appendChild(field("send to", textInput(current.target || "", function (v) {
            applySendTo(current, v);
            draw();
          }, "telegram:8522302999"), TIPS["output.target"]));
        }
        var targetHint = document.createElement("p");
        targetHint.className = "vw-hint";
        targetHint.textContent = channels.length
          ? "A home channel sends a notification; a chat sends there. Collect only just records the result."
          : "Bare platform for its home channel, or platform:chat id for one chat.";
        box.appendChild(targetHint);
      }
    }

    function note(message) {
      el.status.textContent = message || "";
    }

    /**
     * A run's outcome, pinned above the canvas until dismissed or replaced.
     *
     * ``note()`` writes one line into the bar and is wiped by the next action, so a failed
     * or paused run was invisible unless you happened to be looking at the bar. This banner
     * is the opposite: persistent, at the top of the canvas, and announced.
     * kind: "info" (default) | "warn" | "error". Empty message hides it.
     */
    function banner(message, kind) {
      var box = el.banner;
      box.textContent = "";
      if (!message) {
        box.hidden = true;
        box.className = "vw-banner";
        return;
      }
      box.hidden = false;
      box.className = "vw-banner vw-banner-" + (kind || "info");
      var text = document.createElement("p");
      text.textContent = message;
      box.appendChild(text);
      var close = document.createElement("button");
      close.type = "button";
      close.className = "vw-pill";
      close.textContent = "\u2715";
      close.title = "Dismiss this message.";
      close.setAttribute("aria-label", "Dismiss message");
      close.addEventListener("click", function () {
        banner("");
      });
      box.appendChild(close);
    }

    /** Validation problems go to the canvas banner AND the detail box; never a silent word. */
    function showErrors(errors) {
      var list = errors || [];
      if (!list.length) {
        el.errors.textContent = "";
        el.errors.hidden = true;
        return;
      }
      el.errors.hidden = false;
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
      if (kind === "note") fresh.text = "";
      if (typeof x === "number" && typeof y === "number") {
        fresh.x = Math.max(0, Math.round(x - NODE_W / 2));
        fresh.y = Math.max(0, Math.round(y - NODE_H / 2));
      } else {
        var slot = graph.nodes.length;
        fresh.x = 26 + (slot % 4) * 172;
        fresh.y = 28 + Math.floor(slot / 4) * 92;
      }
      graph.nodes.push(fresh);
      selected = id;
      selectedEdge = null;
      setInspector(true);
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
        if (data.valid) {
          note("valid");
          banner("Design is valid \u00b7 " + graph.nodes.length + " node(s).", "info");
        } else {
          note((data.errors || []).length + " problem(s)");
          banner("Not valid \u00b7 " + (data.errors || []).length + " problem(s) \u2014 see the details below the canvas.", "error");
        }
      }).catch(function (err) {
        note("");
        showErrors([{ node: "", field: "request", msg: explain(err) }]);
        banner("Validate failed \u2014 " + explain(err), "error");
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
          banner("Not saved \u2014 " + (data.errors || []).length + " problem(s), see the details below the canvas.", "error");
          return;
        }
        // A refresh is async; remember this name now so pressing Run immediately after Save
        // cannot be refused as "not saved yet".
        if (savedNames.indexOf(data.name) < 0) savedNames.push(data.name);
        showErrors([]);
        note("saved " + data.name + " (" + data.nodes + " node(s))");
        banner("Saved \u201c" + data.name + "\u201d \u00b7 " + data.nodes + " node(s).", "info");
        onSaved();
      }).catch(function (err) {
        note("");
        showErrors([{ node: "", field: "save", msg: explain(err) }]);
        banner("Save failed \u2014 " + explain(err), "error");
      });
    }

    function runDesign() {
      var name = currentName();
      if (!name) {
        showErrors([{ node: "", field: "name", msg: "save the design first" }]);
        banner("Name the design and press Save before running it.", "error");
        return;
      }
      // A draft that was never saved has no server-side design to run: saying so beats a 404.
      // Only gate once the list has actually loaded; before that the POST is authoritative.
      if (designsLoaded && savedNames.indexOf(name) < 0) {
        showErrors([{ node: "", field: "name", msg: name + " is not saved yet" }]);
        note("not run");
        banner("\u201c" + name + "\u201d is not saved yet \u2014 press Save, then Run.", "error");
        return;
      }
      note("running " + name + "\u2026");
      banner("Running \u201c" + name + "\u201d\u2026", "info");
      call(path(name) + "/run", { method: "POST" }).then(function (data) {
        if (data.status === "invalid") {
          showErrors(data.errors || []);
          note("not run");
          banner("Not run \u2014 the design has " + (data.errors || []).length + " problem(s).", "error");
          return;
        }
        showErrors([]);
        renderRun(data);
      }).catch(function (err) {
        note("");
        showErrors([{ node: "", field: "run", msg: explain(err) }]);
        banner("Run failed \u2014 " + explain(err), "error");
      });
    }

    function respondByAgent(nodeId) {
      // Let the host agent produce the parked step's output (the facade a Run uses), then
      // keep going; when the backend is absent the route answers 503 and says so.
      if (!lastRun || !lastRun.run_id) {
        note("no active run");
        return;
      }
      note("asking the agent\u2026");
      call(API + "/runs/" + encodeURIComponent(lastRun.run_id) + "/respond", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: lastRun.run_id, node_id: nodeId, agent_generate: true }),
      }).then(function (data) {
        showErrors([]);
        renderRun(data);
      }).catch(function (err) {
        note("");
        el.run.textContent = explain(err);
        banner("Could not resume the run \u2014 " + explain(err), "error");
      });
    }

    function retryFailedRun() {
      // The same reset ``/workflow run retry <run_id>`` performs: the runner re-enters at the
      // failed step, reusing everything that already produced output. Only a failed run is
      // retried — a parked gate is answered, not restarted.
      if (!lastRun || !lastRun.run_id || lastRun.status !== "failed") {
        note("no failed run");
        return;
      }
      note("retrying\u2026");
      call(API + "/runs/" + encodeURIComponent(lastRun.run_id) + "/retry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      }).then(function (data) {
        showErrors([]);
        renderRun(data);
      }).catch(function (err) {
        note("");
        el.run.textContent = explain(err);
        banner("Could not retry the run \u2014 " + explain(err), "error");
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

    /** "waiting 12m \u00b7 expires in 48m" for a timed gate; "" when it has no deadline. */
    function waitText(pending) {
      if (!pending || !pending.timeout_minutes) return "";
      var since = Number(pending.waiting_since || 0) * 1000;
      if (!since) return "";
      var left = Number(pending.timeout_minutes) * 60000 - (Date.now() - since);
      function span(ms) {
        var minutes = Math.max(0, Math.round(ms / 60000));
        return minutes >= 60 ? Math.round(minutes / 60) + "h" : minutes + "m";
      }
      return left > 0
        ? "waiting " + span(Date.now() - since) + " \u00b7 expires in " + span(left)
        : "past its " + pending.timeout_minutes + "-minute deadline";
    }

    function waitLine(pending) {
      var text = waitText(pending);
      if (!text) return null;
      var node = line("p", text, "vw-hint");
      node.title = TIPS["approval.timeout"];
      return node;
    }

    function renderRun(result) {
      lastRun = result;
      if (result && result.outputs && Object.keys(result.outputs).length) {
        lastOutputs = summarizeOutputs(result);
        lastRunName = result.name || graph.name;
        draw();
      } else {
        // No outputs in this mount (a fresh failure, a parked gate): drop the previous
        // run's excerpts instead of showing stale text next to a new verdict.
        lastOutputs = {};
        lastRunName = "";
      }
      var box = el.run;
      box.textContent = "";
      var status = result.status;
      note(String(status || ""));
      // The run box lives under the canvas where it can be scrolled out of sight; bring it in.
      if (box.scrollIntoView) box.scrollIntoView({ block: "nearest" });

      if (status === "awaiting_approval") {
        var pending = result.pending || {};
        banner("Run " + (result.run_id || "") + " paused at gate " + pending.node_id + " \u2014 answer it below.", "warn");
        box.appendChild(line("h4", "gate " + pending.node_id + ": " + (pending.question || "")));
        if (pending.context) box.appendChild(line("pre", pending.context));
        var wait = waitLine(pending);
        if (wait) box.appendChild(wait);
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
        // A parked agent step means no agent backend was around when the run needed it (an
        // older parked run, or the backend was briefly unavailable). Resume either way: let
        // the agent produce the step now, or paste the result yourself.
        banner(
          "Run " + (result.run_id || "") + " paused at agent step " + step.node_id +
          " \u2014 run this step with the agent, or paste its result below (or run the " +
          "workflow from chat, where the agent executes).",
          "warn"
        );
        box.appendChild(line("h4", "agent step " + step.node_id + " is waiting"));
        box.appendChild(line("pre", step.prompt || ""));
        if (step.context) box.appendChild(line("pre", step.context));
        var agentRun = button("Run this step with the agent", function () {
          respondByAgent(step.node_id);
        });
        agentRun.title = TIPS["runs.agent"];
        box.appendChild(agentRun);
        box.appendChild(line("p", "Or paste the step's result here and press resume \u2014 no chat needed.", "vw-hint"));
        var area = document.createElement("textarea");
        area.rows = 3;
        area.placeholder = "paste the step's output (a JSON object is passed as structured)";
        area.setAttribute("aria-label", "result for agent step " + step.node_id);
        box.appendChild(area);
        var send = button("Send result & resume", function () {
          respond(step.node_id, area.value);
        });
        send.title = TIPS["runs.resume"];
        box.appendChild(send);
        box.appendChild(line("p", "Or run the workflow from chat and the agent executes the step for you.", "vw-hint"));
        return;
      }

      if (status === "failed") {
        var error = result.error || {};
        banner("Run " + (result.run_id || "") + " failed \u2014 " + (error.node_id ? error.node_id + ": " : "") + (error.msg || ""), "error");
        box.appendChild(line("h4", "run failed"));
        box.appendChild(line("pre", (error.node_id ? error.node_id + ": " : "") + (error.msg || "")));
        // A diagnosed failure gets a labelled chip; the hint is the chip's tooltip and the
        // raw message above stays the evidence. No diagnosis, no chip — as before.
        if (error.kind) {
          var chip = line("span", error.kind, "vw-chip");
          chip.title = error.hint || "diagnosed failure kind";
          box.appendChild(chip);
        }
        var retryRun = button("Retry run", function () { retryFailedRun(); });
        retryRun.title = TIPS["runs.retry"];
        box.appendChild(retryRun);
        var failedDelivery = deliveryLine(result);
        if (failedDelivery) box.appendChild(failedDelivery);
        return;
      }

      if (status === "done") {
        var outputs = result.outputs || {};
        banner("Run " + (result.run_id || "") + " finished \u00b7 outputs: " + (Object.keys(outputs).join(", ") || "(none)"), "info");
        box.appendChild(line("h4", "done \u00b7 outputs: " + (Object.keys(outputs).join(", ") || "(none)")));
        if ((result.skipped || []).length) {
          box.appendChild(line("p", "skipped: " + result.skipped.join(", "), "vw-muted"));
        }
        var delivered = deliveryLine(result);
        if (delivered) box.appendChild(delivered);
        box.appendChild(line("pre", JSON.stringify(outputs, null, 2)));
        return;
      }

      banner("Run " + (result.run_id || "") + " \u00b7 " + String(status || "unknown"), "warn");
      box.appendChild(line("h4", String(status || "run")));
      if (result.error) box.appendChild(line("pre", typeof result.error === "string" ? result.error : JSON.stringify(result.error)));
    }

    // ------------------------------------------------------------- wiring up
    function wire() {
      el.name.addEventListener("input", function (ev) {
        graph.name = ev.target.value.trim();
      });
      el.name.title = TIPS["bar.name"];
      q('[data-vw="validate"]').title = TIPS["bar.validate"];
      q('[data-vw="save"]').title = TIPS["bar.save"];
      q('[data-vw="run-now"]').title = TIPS["bar.run"];
      q('[data-vw="delete"]').title = TIPS["bar.delete"];
      q('[data-vw="validate"]').addEventListener("click", validateDraft);
      q('[data-vw="save"]').addEventListener("click", saveDesign);
      q('[data-vw="run-now"]').addEventListener("click", runDesign);
      q('[data-vw="delete"]').addEventListener("click", removeSelected);
      el.toggle.addEventListener("click", function () {
        setInspector(el.app.classList.contains("vw-insp-collapsed"));
      });

      Array.prototype.forEach.call(host.querySelectorAll("[data-kind]"), function (b) {
        var kind = b.getAttribute("data-kind");
        b.title = TIPS[kind] || kind;
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
        if (PALETTE.indexOf(kind) < 0) return;
        var p = svgPoint(ev);
        addNode(kind, p.x, p.y);
      });
    }

    wire();
    watchSize();
    layout();
    el.name.value = graph.name;
    buildInspector();
    draw();

    /** Replace the canvas with a stored graph (or a blank one). */
    function loadGraph(next) {
      // A saved design / template is untrusted input: a non-list `nodes` used to reach
      // layout() and throw, leaving a blank canvas with no explanation.
      var usable = next && typeof next === "object" && Array.isArray(next.nodes)
        && next.nodes.length;
      graph = clone(usable ? next : BLANK);
      graph.nodes = graph.nodes.filter(function (n) {
        return n && typeof n === "object" && typeof n.id === "string" && n.id;
      });
      graph.nodes.forEach(function (n) {
        n.after = Array.isArray(n.after) ? n.after.filter(function (dep) {
          return typeof dep === "string";
        }) : [];
        if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) { delete n.x; delete n.y; }
      });
      if (!graph.name) graph.name = "untitled";
      selected = null;
      selectedEdge = null;
      linkArm = null;
      dragLink = null;
      lastRun = null;
      el.run.textContent = "";
      el.errors.textContent = "";
      el.errors.hidden = true;
      note("");
      banner("");
      el.name.value = graph.name;
      setInspector(false);
      layout();
      buildInspector();
      draw();
    }

    return {
      loadGraph: loadGraph,
      /** Replace the profile/bot list the agent inspector offers. The drawer is rebuilt only
       *  when the user is not typing in it, so a late catalog response cannot wipe an edit. */
      setProfiles: function (list) {
        profiles = Array.isArray(list) ? list : [];
        if (!el.inspector.contains(document.activeElement)) buildInspector();
      },
      /** Replace the model catalog the agent inspector offers, plus the slug of the
       *  host's active provider (only its models can actually run). */
      setModels: function (list, provider) {
        models = Array.isArray(list) ? list : [];
        currentProvider = (provider && String(provider)) || "";
        if (!el.inspector.contains(document.activeElement)) buildInspector();
      },
      /** Replace the delivery targets the output inspector offers. */
      setChannels: function (list) {
        channels = Array.isArray(list) ? list : [];
        if (!el.inspector.contains(document.activeElement)) buildInspector();
      },
      /** Bring a stored run back into the run panel, where its resume box lives. */
      showRun: function (result) {
        renderRun(result);
      },
      /** Names known to exist server-side, so Run can refuse a draft instead of sending a 404. */
      setDesigns: function (list) {
        savedNames = Array.isArray(list) ? list.slice() : [];
        designsLoaded = true;
      },
      /** The draft graph as it would be sent to the backend. */
      getGraph: payloadGraph,
      newDesign: function (name) {
        var blank = clone(BLANK);
        blank.name = name || "untitled";
        loadGraph(blank);
      },
      /** Release what the mount owns: the size observer and any in-flight drag listeners. */
      destroy: function () {
        if (gestureCleanup) gestureCleanup();
        if (sizeObserver) {
          sizeObserver.disconnect();
          sizeObserver = null;
        }
        el.inspector.textContent = "";
      },
    };
  }

  // ------------------------------------------------------------- schedules view
  /** The cron jobs this plugin created, with the four controls that matter. A job that
   *  cannot be read is stated, never shown as an empty list pretending to be the truth. */
  function SchedulesPanel(props) {
    var designs = props.designs || [];
    var [jobs, setJobs] = useState([]);
    var [note, setNote] = useState("");
    var [busy, setBusy] = useState("");
    var [name, setName] = useState("");
    var [preset, setPreset] = useState("daily");
    var [time, setTime] = useState("09:00");
    var [weekday, setWeekday] = useState("mon");
    var [cron, setCron] = useState("");

    var fresh = useCallback(function () {
      return fetchJSON(API + "/schedules").then(function (data) {
        setJobs((data && data.jobs) || []);
        if (!data || !data.available) {
          setNote("The host scheduler could not be read here \u2014 nothing is listed.");
        }
      }).catch(function (err) {
        setNote(explain(err));
      });
    }, []);

    useEffect(function () {
      fresh();
    }, [fresh]);

    function act(job, action) {
      setBusy(job.job_id);
      fetchJSON(API + "/schedules/" + encodeURIComponent(job.job_id) + "/" + action, {
        method: "POST",
      }).then(function (data) {
        setBusy("");
        if (!data || !data.ok) {
          setNote((data && data.error) || "the scheduler refused it");
          return;
        }
        setNote(action + " \u00b7 " + (job.design || job.name));
        fresh();
      }).catch(function (err) {
        setBusy("");
        setNote(explain(err));
      });
    }

    function schedule() {
      if (!name) {
        setNote("pick a workflow first");
        return;
      }
      var expression = buildCron(preset, time, weekday, cron);
      var problem = cronProblem(expression);
      if (problem) {
        setNote(problem);
        return;
      }
      setNote("scheduling\u2026");
      fetchJSON(API + "/designs/" + encodeURIComponent(name) + "/schedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preset: preset, time: time, weekday: weekday, cron: expression }),
      }).then(function (data) {
        if (!data || !data.ok) {
          setNote((data && data.error) || "the scheduler refused it");
          return;
        }
        setNote((data.created ? "scheduled " : "updated ") + name + " \u00b7 " +
          describeCron(data.cron || expression));
        fresh();
      }).catch(function (err) {
        setNote(explain(err));
      });
    }

    var rows = jobs.map(function (job) {
      var id = job.job_id;
      return h("div", { key: id || job.name, className: "vw-job" },
        h("div", { className: "vw-job-head" },
          h("strong", null, job.design || job.name),
          h("span", { className: "vw-muted" }, " \u00b7 " + job.state +
            (job.next_run_at ? " \u00b7 next " + job.next_run_at : ""))),
        h("p", { className: "vw-hint" }, describeCron(job.schedule) + "  (" + job.schedule + ")"),
        h("div", { className: "vw-job-actions" },
          h("button", {
            type: "button", className: "vw-pill", title: TIPS["schedules.pause"],
            disabled: busy === id || job.state === "paused",
            onClick: function () { act(job, "pause"); },
          }, "Pause"),
          h("button", {
            type: "button", className: "vw-pill", title: TIPS["schedules.resume"],
            disabled: busy === id || job.state !== "paused",
            onClick: function () { act(job, "resume"); },
          }, "Resume"),
          h("button", {
            type: "button", className: "vw-pill", title: TIPS["schedules.run"],
            disabled: busy === id,
            onClick: function () { act(job, "run"); },
          }, "Run now"),
          h("button", {
            type: "button", className: "vw-pill", title: TIPS["schedules.remove"],
            disabled: busy === id,
            onClick: function () { act(job, "remove"); },
          }, "Delete")));
    });

    var picker = h("div", { className: "vw-sched-form" },
      h("div", { className: "vw-label", title: TIPS["bar.name"] }, "workflow"),
      h("select", {
        value: name, title: TIPS["bar.name"],
        onChange: function (ev) { setName(ev.target.value); },
      }, [h("option", { key: "", value: "" }, "\u2014 pick a saved workflow \u2014")]
        .concat(designs.map(function (d) { return h("option", { key: d, value: d }, d); }))),
      h("div", { className: "vw-label", title: TIPS["trigger.preset"] }, "runs"),
      h("select", {
        value: preset, title: TIPS["trigger.preset"],
        onChange: function (ev) { setPreset(ev.target.value); },
      }, PRESETS.map(function (p) {
        return h("option", { key: p, value: p, title: TIPS["presets." + p] }, PRESET_LABELS[p]);
      })),
      preset === "weekly" ? h("select", {
        value: weekday, title: TIPS["trigger.weekday"],
        onChange: function (ev) { setWeekday(ev.target.value); },
      }, WEEKDAYS.map(function (pair) {
        return h("option", { key: pair[0], value: pair[0], title: TIPS["trigger.weekday"] }, pair[1]);
      })) : null,
      preset === "custom" ? null : h("input", {
        type: "text", value: time, title: TIPS["trigger.time"],
        onChange: function (ev) { setTime(ev.target.value); },
      }),
      preset === "custom" ? h("input", {
        type: "text", value: cron, placeholder: "0 9 * * 1-5", title: TIPS["trigger.schedule"],
        onChange: function (ev) { setCron(ev.target.value); },
      }) : null,
      h("button", {
        type: "button", className: "vw-pill", title: TIPS["schedules.create"],
        onClick: schedule,
      }, "Schedule it"),
      h("p", { className: "vw-hint", title: TIPS["trigger.schedule"] },
        describeCron(buildCron(preset, time, weekday, cron)) +
        "  (" + (buildCron(preset, time, weekday, cron) || "no cron yet") + ")"));

    return h("div", { className: "vw-sched" },
      h("p", { className: "vw-rail-title" }, "Scheduled runs"),
      rows.length ? h("div", { className: "vw-list" }, rows)
        : h("p", { className: "vw-muted" }, "No scheduled workflows yet."),
      note ? h("p", { className: "vw-hint" }, note) : null,
      picker);
  }

  // ---------------------------------------------------------------- runs view
  /**
   * Every run saved on disk, newest first — not just the one this tab started.
   *
   * A run begun by the chat tool, a cron job or another browser was previously invisible and
   * unanswerable here; a paused gate now offers its options inline so it can be answered from
   * the list without reopening the design.
   */
  function RunsPanel(props) {
    var [runs, setRuns] = useState([]);
    var [note, setNote] = useState("");
    var [busy, setBusy] = useState("");

    var fresh = useCallback(function () {
      return fetchJSON(API + "/runs?limit=20").then(function (data) {
        setRuns((data && data.runs) || []);
      }).catch(function (err) {
        setNote(explain(err));
      });
    }, []);

    useEffect(function () {
      fresh();
    }, [fresh]);

    function answer(row, option) {
      setBusy(row.run_id);
      setNote("resuming \u2026");
      fetchJSON(API + "/runs/" + encodeURIComponent(row.run_id) + "/respond", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: row.run_id, node_id: row.node_id, answer: option }),
      }).then(function (data) {
        setBusy("");
        setNote(row.run_id + ": " + ((data && data.status) || "no status"));
        fresh();
      }).catch(function (err) {
        setBusy("");
        setNote(explain(err));
      });
    }

    function retryRow(row) {
      setBusy(row.run_id);
      setNote("retrying \u2026");
      fetchJSON(API + "/runs/" + encodeURIComponent(row.run_id) + "/retry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      }).then(function (data) {
        setBusy("");
        setNote(row.run_id + ": " + ((data && data.status) || "no status"));
        fresh();
      }).catch(function (err) {
        setBusy("");
        setNote(explain(err));
      });
    }

    /** "3m ago" — the row has to say how old a waiting gate is. */
    function when(seconds) {
      var age = Math.max(0, Math.round(Date.now() / 1000 - Number(seconds || 0)));
      if (age < 60) return age + "s ago";
      if (age < 3600) return Math.round(age / 60) + "m ago";
      if (age < 86400) return Math.round(age / 3600) + "h ago";
      return Math.round(age / 86400) + "d ago";
    }

    var rows = runs.map(function (row) {
      var isGate = row.status === "awaiting_approval";
      var isAgent = row.status === "awaiting_agent";
      var actions = [];
      if (isGate) {
        (row.options || []).forEach(function (option) {
          actions.push(h("button", {
            key: "opt-" + option, type: "button", className: "vw-pill",
            title: TIPS["runs.approve"], disabled: busy === row.run_id,
            onClick: function () { answer(row, option); },
          }, option));
        });
      }
      if (isAgent) {
        actions.push(h("button", {
          key: "answer", type: "button", className: "vw-pill",
          title: TIPS["runs.resume"], disabled: busy === row.run_id,
          onClick: function () { props.onAnswer(row); },
        }, "Answer"));
      }
      if (row.status === "failed") {
        actions.push(h("button", {
          key: "retry", type: "button", className: "vw-pill",
          title: TIPS["runs.retry"], disabled: busy === row.run_id,
          onClick: function () { retryRow(row); },
        }, "Retry"));
      }
      if (row.status === "done") {
        actions.push(h("button", {
          key: "result", type: "button", className: "vw-pill",
          title: TIPS["runs.result"], disabled: busy === row.run_id,
          onClick: function () { props.onResult(row); },
        }, "Result"));
      }
      actions.push(h("button", {
        key: "open", type: "button", className: "vw-pill", title: TIPS["runs.open"],
        onClick: function () { props.onOpen(row.name); },
      }, "Open"));
      return h("div", { key: row.run_id, className: "vw-job" },
        h("div", { className: "vw-job-head" },
          h("strong", null, row.name || "(unnamed)"),
          h("span", { className: "vw-muted" }, " \u00b7 " + row.status + " \u00b7 " +
            row.run_id + " \u00b7 " + when(row.updated))),
        isGate
          ? h("p", { className: "vw-hint" }, "gate " + row.node_id + ": " + (row.question || ""))
          : null,
        isGate && waitText(row)
          ? h("p", { className: "vw-hint", title: TIPS["approval.timeout"] }, waitText(row))
          : null,
        isGate && !(row.options || []).length
          ? h("p", { className: "vw-hint" }, "This gate takes free text \u2014 answer it in chat.")
          : null,
        isAgent
          ? h("p", { className: "vw-hint" },
              "agent step " + row.node_id + " is paused \u2014 answer it in the run panel, or from chat.")
          : null,
        row.error
          ? h("p", { className: "vw-error" },
              (row.error.node_id ? row.error.node_id + ": " : "") + (row.error.msg || ""),
              row.error.kind
                ? h("span", { className: "vw-chip",
                    title: row.error.hint || "diagnosed failure kind" }, " " + row.error.kind)
                : null)
          : null,
        (row.deliveries || []).length
          ? h("p", { className: "vw-hint" }, "delivery: " + row.deliveries.map(function (d) {
              return (d.ok ? "sent " : "FAILED ") + d.node_id + " \u2192 " + (d.target || "?");
            }).join(" \u00b7 "))
          : null,
        h("div", { className: "vw-job-actions" }, actions));
    });

    return h("div", { className: "vw-sched" },
      h("p", { className: "vw-rail-title" }, "Runs"),
      h("p", { className: "vw-hint" },
        "Every run saved on this machine, newest first \u2014 including runs started in chat " +
        "or by a schedule."),
      rows.length ? h("div", { className: "vw-list" }, rows)
        : h("p", { className: "vw-muted" }, "No runs yet."),
      note ? h("p", { className: "vw-hint" }, note) : null,
      h("button", {
        type: "button", className: "vw-pill", title: TIPS["runs.refresh"],
        onClick: function () { fresh(); },
      }, "Refresh"));
  }

  // ---------------------------------------------------------------- React tab
  function WorkflowsTab() {
    var hostRef = useRef(null);
    var designerRef = useRef(null);
    var [designs, setDesigns] = useState([]);
    var [templates, setTemplates] = useState([]);
    var [active, setActive] = useState("");
    var [view, setView] = useState("designer");
    var [error, setError] = useState("");

    var refresh = useCallback(function () {
      return fetchJSON(API + "/designs").then(function (data) {
        setDesigns((data && data.designs) || []);
        // Run needs to know which names exist server-side, so a draft is refused with a
        // sentence instead of a 404 nobody sees.
        if (designerRef.current) designerRef.current.setDesigns((data && data.designs) || []);
      }).catch(function (err) {
        setError(explain(err));
      });
    }, []);

    // Profiles ("bots") and the model catalog are listed once per mount; a failure is not
    // fatal — the agent picker has nothing to offer and the model field stays typeable.
    var loadProfiles = useCallback(function () {
      return fetchJSON(API + "/profiles").then(function (data) {
        if (designerRef.current) designerRef.current.setProfiles((data && data.profiles) || []);
      }).catch(function () {
        if (designerRef.current) designerRef.current.setProfiles([]);
      });
    }, []);

    // The host catalog behind the model dropdown: providers with their model ids. An empty
    // answer (no host package) leaves the agent node's model field a free-text input.
    var loadModels = useCallback(function () {
      return fetchJSON(API + "/models").then(function (data) {
        if (designerRef.current) designerRef.current.setModels((data && data.providers) || [],
          (data && data.current && data.current["provider"]) || "");
      }).catch(function () {
        if (designerRef.current) designerRef.current.setModels([], "");
      });
    }, []);

    // Built-in starting points ship with the plugin; an empty list is honest (older install,
    // or a stale copy) and the canvas then offers only a blank design.
    var loadTemplates = useCallback(function () {
      return fetchJSON(API + "/designs/templates").then(function (data) {
        setTemplates((data && data.templates) || []);
      }).catch(function () {
        setTemplates([]);
      });
    }, []);

    // Delivery targets come from the host's own channel directory; a failure only means the
    // output node keeps its free-text field.
    var loadChannels = useCallback(function () {
      return fetchJSON(API + "/channels").then(function (data) {
        if (designerRef.current) designerRef.current.setChannels((data && data.channels) || []);
      }).catch(function () {
        if (designerRef.current) designerRef.current.setChannels([]);
      });
    }, []);

    useEffect(function () {
      if (!hostRef.current) return undefined;
      designerRef.current = createDesigner(hostRef.current, {
        fetchJSON: fetchJSON,
        onSaved: refresh,
      });
      refresh();
      loadTemplates();
      loadProfiles();
      loadModels();
      loadChannels();
      return function () {
        if (designerRef.current) designerRef.current.destroy();
        designerRef.current = null;
      };
    }, [refresh, loadTemplates, loadProfiles, loadModels, loadChannels]);

    function open(name) {
      setActive(name);
      setError("");
      fetchJSON(API + "/designs/" + encodeURIComponent(name)).then(function (data) {
        if (designerRef.current) designerRef.current.loadGraph(data.graph);
      }).catch(function (err) {
        setError(explain(err));
      });
    }

    // A finished run's text lives only on disk; "Result" mounts it in the run panel
    // through the same single-run fetch the Answer path uses.
    function showStoredResult(row) {
      if (!row || !row.run_id) return;
      setView("designer");
      fetchJSON(API + "/runs/" + encodeURIComponent(row.run_id)).then(function (run) {
        if (designerRef.current && run) designerRef.current.showRun(run);
      }).catch(function (err) {
        setError(explain(err));
      });
    }
    function answerStored(row) {
      if (!row || !row.name) return;
      open(row.name);
      // A paused agent step is answered in the run panel, so "Answer" lands the user
      // there with that run mounted — the whole point is to remove the "go somewhere
      // else" dead end.
      setView("designer");
      fetchJSON(API + "/runs/" + encodeURIComponent(row.run_id)).then(function (run) {
        if (designerRef.current && run) designerRef.current.showRun(run);
      }).catch(function (err) {
        setError(explain(err));
      });
    }

    function blank() {
      setActive("");
      setError("");
      if (designerRef.current) designerRef.current.newDesign("untitled");
    }

    // A template is a draft, not a saved design: it loads onto the canvas and the user saves it
    // under their own name, so two people can start from "Review gate" without colliding.
    function useTemplate(name) {
      var row = null;
      for (var i = 0; i < templates.length; i += 1) {
        if (templates[i].name === name) row = templates[i];
      }
      if (!row) return;
      setActive("");
      setError("");
      if (designerRef.current) designerRef.current.loadGraph(row.graph);
    }

    // One compact row instead of a 190px rail: at 760px of tab width every column the rail
    // took came straight out of the canvas.
    var top = h("div", { key: "top", className: "vw-top" },
      h("div", { key: "views", className: "vw-views" },
        h("button", {
          key: "designer", type: "button", className: "vw-pill",
          "aria-pressed": view === "designer" ? "true" : "false",
          onClick: function () { setView("designer"); },
        }, "Designer"),
        h("button", {
          key: "runs", type: "button", className: "vw-pill",
          "aria-pressed": view === "runs" ? "true" : "false",
          onClick: function () { setView("runs"); },
        }, "Runs"),
        h("button", {
          key: "schedules", type: "button", className: "vw-pill",
          "aria-pressed": view === "schedules" ? "true" : "false",
          onClick: function () { setView("schedules"); },
        }, "Schedules")),
      h("select", {
        key: "designs",
        className: "vw-grow",
        "aria-label": "saved workflows",
        title: "Open a saved workflow, or keep the draft on the canvas.",
        value: active,
        onChange: function (ev) {
          if (ev.target.value) open(ev.target.value);
        },
      },
        h("option", { key: "none", value: "" },
          designs.length ? "\u2014 saved workflows \u2014" : "no saved workflows yet"),
        designs.map(function (name) {
          return h("option", { key: name, value: name }, name);
        })),
      h("select", {
        key: "templates",
        className: "vw-grow",
        "aria-label": "start from a template",
        title: TIPS["bar.templates"],
        value: "",
        disabled: !templates.length,
        onChange: function (ev) { if (ev.target.value) useTemplate(ev.target.value); },
      },
        h("option", { key: "none", value: "" },
          templates.length ? "\u2014 start from a template \u2014" : "no templates"),
        templates.map(function (row) {
          return h("option", { key: row.name, value: row.name, title: row.description },
            row.title);
        })),
      h("button", { key: "new", type: "button", className: "vw-pill",
        title: TIPS["bar.new"], onClick: blank }, "New"),
      error ? h("p", { key: "err", className: "vw-error" }, error) : null
    );

    return h(
      "div",
      { className: "vw-shell" },
      h("style", null, CSS),
      top,
      view === "schedules"
        ? h("div", { className: "vw-stage vw-stage-sched" }, h(SchedulesPanel, { designs: designs }))
        : view === "runs"
          ? h("div", { className: "vw-stage vw-stage-sched" },            h(RunsPanel, {
              onOpen: function (name) {
                if (!name) return;
                open(name);
                setView("designer");
              },
              onAnswer: answerStored,
              onResult: showStoredResult,
            }))
          : h("div", { className: "vw-stage", ref: hostRef })
    );
  }

  PLUGINS.register("visual-workflow", WorkflowsTab);
})();
