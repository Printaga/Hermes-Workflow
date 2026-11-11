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
 *   GET  /designs/templates           built-in designs shipped in examples/
 *   GET  /designs/{name}              one graph
 *   POST /designs/{name}              validate + save a graph
 *   POST /designs/{name}/validate     validate a saved design or a draft {"graph": ...}
 *   POST /designs/{name}/run          run now, until done or paused
 *   POST /runs/{run_id}/respond       answer an approval gate / a pending agent step
 */
import { jsx } from "react/jsx-runtime";

const SVG_NS = "http://www.w3.org/2000/svg";
const KINDS = ["trigger", "agent", "condition", "approval", "output"];
// A sticky note: legal canvas content, never a step. `KINDS` stays the five runnable kinds
// (the palette list below adds the note), so nothing that validates or converts a workflow
// can mistake an annotation for work. Mirrors NOTE_KIND in visual_workflow_hermes/schema.py.
const NOTE = "note";
const NOTE_COLORS = ["yellow", "blue", "green", "red"];
const PALETTE = KINDS.concat([NOTE]);
const MODES = ["manual", "schedule"];

// ---- tooltips ---------------------------------------------------------------
// One table, one wording, all three surfaces (dashboard/dist/index.js, desktop/plugin.js,
// widgets/designer.html). A native `title` is the smallest mechanism that works in a hosted
// page, inside SVG and in a standalone file alike; tests/test_tooltips.py asserts every node
// kind and every inspector option has a real sentence here.
const TIPS = {
  trigger: "Starts the run: by hand when you press Run, or on a Hermes schedule you pick.",
  agent: "Asks a bot to do one step and waits for its reply.",
  condition: "Compares a field from an earlier step and skips the branch when the test fails.",
  approval: "Pauses the run and asks a person to choose or type an answer.",    output: "Collects the results, and can send them to one of your chats.",
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
  "output.target": "Where it goes: a platform for its home channel, or platform:chat id like telegram:8522302999.",
    "note.text": "What the sticky says; it is only for the person reading the canvas.",
    "note.color": "Tint for the sticky; it is a reading aid, not part of the run.",
  "schedule.save": "Create or update the real Hermes cron job that replays this saved workflow.",
  "bar.name": "Name this workflow is saved and run under.",
  "bar.templates": "Start from a built-in workflow: it loads onto the canvas, and Save stores it under your own name.",
  "bar.new": "Start from an empty canvas.",
  "bar.validate": "Check the graph without saving it.",
  "bar.save": "Validate and store the workflow.",
  "bar.run": "Run it now: advance until it finishes or pauses at a gate.",
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
const PRESETS = ["daily", "weekdays", "weekly", "hourly", "custom"];
const PRESET_LABELS = {
  daily: "Every day",
  weekdays: "Monday to Friday",
  weekly: "Once a week",
  hourly: "Every hour",
  custom: "Advanced (cron)",
};
const WEEKDAYS = [
  ["mon", "Monday"], ["tue", "Tuesday"], ["wed", "Wednesday"], ["thu", "Thursday"],
  ["fri", "Friday"], ["sat", "Saturday"], ["sun", "Sunday"],
];
const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const CRON_FIELDS = [
  ["minute", 0, 59], ["hour", 0, 23], ["day-of-month", 1, 31], ["month", 1, 12],
  ["day-of-week", 0, 7],
];

const pad2 = (value) => (value < 10 ? "0" : "") + value;

/** ``"09:30"`` -> ``[9, 30]``; null when it is not a 24h HH:MM. */
function timeParts(value) {
  const m = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(String(value || "").trim());
  return m ? [parseInt(m[1], 10), parseInt(m[2], 10)] : null;
}

function weekdayIndex(name) {
  const key = String(name || "").slice(0, 3).toLowerCase();
  const i = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"].indexOf(key);
  return i < 0 ? 1 : i;
}

/** Preset picker values -> the cron expression that gets saved. */
function buildCron(preset, time, weekday, custom) {
  if (preset === "custom") return String(custom || "").trim();
  const parts = timeParts(time);
  if (!parts) return "";
  const hour = parts[0];
  const minute = parts[1];
  if (preset === "hourly") return minute + " * * * *";
  if (preset === "daily") return minute + " " + hour + " * * *";
  if (preset === "weekdays") return minute + " " + hour + " * * 1-5";
  return minute + " " + hour + " * * " + weekdayIndex(weekday);
}

function cronFieldOk(raw, low, high) {
  const parts = String(raw).split(",");
  for (let i = 0; i < parts.length; i += 1) {
    let part = parts[i].trim();
    if (!part) return false;
    if (part.indexOf("/") >= 0) {
      const step = part.split("/");
      // Exactly one step segment: "*/15/2" and "5/10/extra" are not valid cron.
      if (step.length !== 2) return false;
      part = step[0];
      if (!/^\d+$/.test(step[1] || "") || parseInt(step[1], 10) < 1) return false;
    }
    if (part === "*") continue;
    if (part.indexOf("-") >= 0) {
      const span = part.split("-");
      if (!/^\d+$/.test(span[0] || "") || !/^\d+$/.test(span[1] || "")) return false;
      const from = parseInt(span[0], 10);
      const to = parseInt(span[1], 10);
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
  const text = String(expression || "").trim();
  if (!text) return "enter a cron expression (5 fields, e.g. 0 9 * * 1-5)";
  const fields = text.split(/\s+/);
  if (fields.length !== 5) {
    return "cron needs 5 fields (minute hour day month weekday), got " + fields.length;
  }
  for (const spec of CRON_FIELDS) {
    const field = fields[CRON_FIELDS.indexOf(spec)];
    if (!cronFieldOk(field, spec[1], spec[2])) {
      return spec[0] + " field " + field + " is not valid (allowed " + spec[1] + "-" + spec[2] +
        ", *, */n, a-b)";
    }
  }
  return "";
}

/** Plain words for a cron expression, so the canvas reads without decoding cron. */
function describeCron(expression) {
  const text = String(expression || "").trim();
  if (cronProblem(text)) return text;
  const f = text.split(/\s+/);
  if (f[2] !== "*" || f[3] !== "*") return "custom schedule";
  if (f[1] === "*") {
    // "* * * * *" is valid cron (no fixed minute), so guard the cast or this reads ":NaN".
    return /^\d+$/.test(f[0]) ? "every hour at :" + pad2(parseInt(f[0], 10)) : "every hour";
  }
  if (!/^\d+$/.test(f[0]) || !/^\d+$/.test(f[1])) return "custom schedule";
  const at = pad2(parseInt(f[1], 10)) + ":" + pad2(parseInt(f[0], 10));
  if (f[4] === "*") return "every day at " + at;
  if (f[4] === "1-5") return "Monday to Friday at " + at;
  const name = /^\d+$/.test(f[4]) ? DAY_NAMES[parseInt(f[4], 10) % 7] : "";
  return name ? "every " + name + " at " + at : "custom schedule";
}

/** The preset a saved cron expression reads as; "custom" when it fits none. */
function presetOf(expression) {
  const text = String(expression || "").trim();
  if (cronProblem(text)) return "custom";
  const f = text.split(/\s+/);
  if (f[2] !== "*" || f[3] !== "*") return "custom";
  if (f[1] === "*") return /^\d+$/.test(f[0]) ? "hourly" : "custom";
  if (!/^\d+$/.test(f[0]) || !/^\d+$/.test(f[1])) return "custom";
  if (f[4] === "1-5") return "weekdays";
  if (f[4] === "*") return "daily";
  // A list/step weekday (e.g. "1,3") has no weekly-picker equivalent; calling it weekly
  // would coerce it to one day when the picker rebuilds the expression.
  return /^\d+$/.test(f[4]) ? "weekly" : "custom";
}

function timeOf(expression) {
  const f = String(expression || "").trim().split(/\s+/);
  if (f.length === 5 && /^\d+$/.test(f[0]) && /^\d+$/.test(f[1])) {
    return pad2(parseInt(f[1], 10)) + ":" + pad2(parseInt(f[0], 10));
  }
  return "09:00";
}

function weekdayOf(expression) {
  const f = String(expression || "").trim().split(/\s+/);
  if (f.length === 5 && /^\d+$/.test(f[4])) {
    // cron day-of-week is 0=Sunday..6=Saturday (7 is Sunday too); WEEKDAYS starts at Monday.
    const dayName = DAY_NAMES[parseInt(f[4], 10) % 7];
    const hit = WEEKDAYS.find((pair) => pair[1] === dayName);
    return hit ? hit[0] : "mon";
  }
  return "mon";
}
// Compact cards: the canvas is often 600px wide inside a window that already has a chat
// sidebar open, so a node is 150x58 and its preview is at most two short lines.
const NODE_W = 150;
const NODE_H = 58;
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
  // JSON, not "from>to": an id may itself contain '>', and the key is also parsed back
  // when a selected edge is deleted. JSON keeps the pair unambiguous without a charset rule.
  return JSON.stringify([from, to]);
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
  ".vw-shell{--vw-ink:var(--midground,#ffe6cb);--vw-dim:color-mix(in srgb,var(--midground,#ffe6cb) 72%,transparent);--vw-surface:color-mix(in srgb,var(--midground,#ffe6cb) 5%,var(--background,#041c1c));--vw-line:color-mix(in srgb,var(--midground,#ffe6cb) 16%,transparent);--vw-node:color-mix(in srgb,var(--midground,#ffe6cb) 7%,var(--background,#041c1c));--vw-note-yellow:color-mix(in srgb,#f2d16b 20%,var(--background,#041c1c));--vw-note-blue:color-mix(in srgb,#6ea8fe 20%,var(--background,#041c1c));--vw-note-green:color-mix(in srgb,#34d399 20%,var(--background,#041c1c));--vw-note-red:color-mix(in srgb,#fb2c36 20%,var(--background,#041c1c));--vw-accent:var(--series-output-token,#34d399);--vw-danger:#fb2c36;display:flex;flex-direction:column;height:100%;min-height:420px;min-width:0;font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--vw-ink);text-align:left}",
  ".vw-rail-title{margin:0 0 6px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--vw-dim)}",
  ".vw-list{display:flex;flex-direction:column;gap:4px;margin:0 0 10px}",
  ".vw-top{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:6px 8px;border-bottom:1px solid var(--vw-line);background:var(--vw-surface)}",
  ".vw-top .vw-grow{flex:1 1 160px;min-width:120px}",
  ".vw-stage{flex:1 1 auto;min-width:0;display:flex;flex-direction:column}",
  // flex:0 0 auto keeps the app content-sized: as a growing item it took whatever height the
  // host guessed at load and then collapsed when a node was selected, so the surface moved
  // under the pointer on the first click.
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
  ".vw-main{display:flex;flex:1 1 auto;min-height:0;min-width:0}",
  // The canvas asks for its own band instead of inheriting whatever the shell left over, so
  // opening the inspector can never take the drawing surface away.
  ".vw-wrap{flex:1 1 auto;min-width:0;min-height:clamp(320px,calc(100dvh - 240px),900px);overflow:auto;padding:6px}",
  ".vw-inspector{flex:0 0 auto;width:252px;box-sizing:border-box;padding:4px 0 8px 10px;border-left:1px solid var(--vw-line);overflow:auto}",
  ".vw-insp-toggle{font:inherit;color:var(--vw-dim);background:none;border:0;padding:2px 4px;cursor:pointer;text-align:left}",
  ".vw-insp-toggle:hover{color:var(--vw-ink)}",
  ".vw-app.vw-insp-collapsed .vw-inspector{width:30px;padding:4px 2px;overflow:hidden}",
  ".vw-app.vw-insp-collapsed .vw-insp-body{display:none}",
  // No height:100% here: a percentage inside an auto-height row is a cyclic dependency, and
  // Chrome settled it at ~911px — the phantom band the canvas lost on the first selection.
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
  ".vw-shell [hidden]{display:none!important}",
  ".vw-sched{flex:1 1 auto;min-width:0;overflow:auto;padding:8px 10px}",
  ".vw-job{padding:6px 0;border-bottom:1px solid var(--vw-line)}",
  ".vw-job-head{display:flex;gap:4px;align-items:baseline}",
  ".vw-job-actions{display:flex;gap:4px;margin-top:4px}",
  ".vw-sched-form{display:flex;flex-direction:column;gap:2px;max-width:320px;margin-top:10px}",
].join("\n");

const TEMPLATE =
  '  <div class="vw-top">' +
  '    <div class="vw-views">' +
  '      <button class="vw-pill" type="button" data-vw="view-designer" aria-pressed="true">Designer</button>' +
  '      <button class="vw-pill" type="button" data-vw="view-runs" aria-pressed="false">Runs</button>' +
  '      <button class="vw-pill" type="button" data-vw="view-schedules" aria-pressed="false">Schedules</button>' +
  "    </div>" +
  '    <select class="vw-grow" data-vw="designs" aria-label="saved workflows"></select>' +
  '    <select class="vw-grow" data-vw="templates" aria-label="start from a template"></select>' +
  '    <button class="vw-pill" type="button" data-vw="new">New</button>' +
  '    <p class="vw-error" data-vw="rail-error"></p>' +
  "  </div>" +
  '  <div class="vw-stage">' +
  '  <div class="vw-sched" data-vw="sched" hidden></div>' +
  '  <div class="vw-sched" data-vw="runs" hidden></div>' +
  '  <div class="vw-app vw-insp-collapsed">' +
  '    <div class="vw-kit">' +
  '      <button class="vw-pill vw-tool" type="button" draggable="true" data-kind="trigger"><span class="ico">\u25b6</span>Trigger</button>' +
  '      <button class="vw-pill vw-tool" type="button" draggable="true" data-kind="agent"><span class="ico">\u2726</span>Agent</button>' +
  '      <button class="vw-pill vw-tool" type="button" draggable="true" data-kind="condition"><span class="ico">\u25c7</span>Condition</button>' +
  '      <button class="vw-pill vw-tool" type="button" draggable="true" data-kind="approval"><span class="ico">\u2713</span>Approval</button>' +
  '      <button class="vw-pill vw-tool" type="button" draggable="true" data-kind="output"><span class="ico">\u25a4</span>Output</button>' +
  '      <button class="vw-pill vw-tool" type="button" draggable="true" data-kind="note"><span class="ico">\u270e</span>Note</button>' +
  '      <p class="vw-kit-hint">Click a node to add it, or drag it onto the canvas. Drag a node&rsquo;s right port to another node&rsquo;s left port.</p>' +
  "    </div>" +
  '    <div class="vw-bar">' +
  '      <input class="vw-grow" data-vw="name" type="text" value="untitled" aria-label="design name">' +
  '      <button class="vw-pill" type="button" data-vw="validate">Validate</button>' +
  '      <button class="vw-pill" type="button" data-vw="save">Save</button>' +
  '      <button class="vw-pill" type="button" data-vw="run-now">Run</button>' +
  '      <button class="vw-pill" type="button" data-vw="delete">Delete</button>' +
  '      <span class="vw-muted" data-vw="status"></span>' +
  "    </div>" +
  '    <div class="vw-banner" data-vw="banner" role="status" aria-live="polite" aria-atomic="true" hidden></div>' +
  '    <div class="vw-main">' +
  '      <div class="vw-wrap" data-vw="wrap">' +
  '        <svg class="vw-canvas" data-vw="canvas" role="img" aria-label="workflow canvas"></svg>' +
  "      </div>" +
  '      <div class="vw-inspector">' +
  '        <button class="vw-insp-toggle" type="button" data-vw="insp-toggle" aria-expanded="false" aria-controls="vw-insp-body">Inspector</button>' +
  '        <div class="vw-insp-body" id="vw-insp-body" data-vw="inspector"></div>' +
  "      </div>" +
  "    </div>" +
  '    <div class="vw-run" data-vw="run"></div>' +
  '    <pre class="vw-errors" data-vw="errors" hidden></pre>' +
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
 * Mount the designer (top bar · node bar · SVG graph · collapsible inspector · run box) into
 * *host*.
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
    app: q(".vw-app"),
    sched: q('[data-vw="sched"]'),
    runs: q('[data-vw="runs"]'),
    designs: q('[data-vw="designs"]'),
    templates: q('[data-vw="templates"]'),
    railError: q('[data-vw="rail-error"]'),
    name: q('[data-vw="name"]'),
    canvas: q('[data-vw="canvas"]'),
    wrap: q('[data-vw="wrap"]'),
    toggle: q('[data-vw="insp-toggle"]'),
    inspector: q('[data-vw="inspector"]'),
    errors: q('[data-vw="errors"]'),
    status: q('[data-vw="status"]'),
    banner: q('[data-vw="banner"]'),
    run: q('[data-vw="run"]'),
  };

  let graph = clone(BLANK);
  let designs = [];
  let templates = [];  // built-in starting points shipped in examples/
  let active = "";
  let selected = null;
  let selectedEdge = null;
  let linkArm = null;   // source node id after a click on an output port
  let dragLink = null;  // live drag from an output port: {from, x1, y1, x2, y2}
  let profiles = [];    // host profiles ("bots") offered to agent nodes
  let models = [];      // host model catalog: [{slug, label, models}]
  // Slug of the host's active provider ("" when unknown): only its models can
  // actually run, so the picker offers those. Set alongside the catalog.
  let currentProvider = "";
  let channels = [];    // delivery targets ("chats") offered to output nodes
  let lastRun = null;
  // Latest mounted run's outputs by node id, painted under their nodes by draw().
  // Kept with the run's design name so switching designs never paints stale text.
  let lastOutputs = {};
  let lastRunName = "";
  let savedNames = [];  // names known to exist server-side; Run refuses a draft instead of 404ing
  let designsLoaded = false;  // only gate Run once GET /designs actually succeeded
  let sizeObserver = null;    // kept so an unmount can disconnect it
  let gestureCleanup = null;  // cancels an in-flight drag/link on unmount or window blur

  function nodeById(id) {
    const hits = graph.nodes.filter((n) => n.id === id);
    return hits[0] || null;
  }

  function layout() {
    graph.nodes.forEach((n, i) => {
      if (typeof n.x !== "number" || typeof n.y !== "number") {
        n.x = 26 + (i % 4) * 172;
        n.y = 28 + Math.floor(i / 4) * 92;
      }
    });
  }

  /** Notes carry one of a fixed set of tints; anything else reads as the default yellow. */
  function noteColor(n) {
    const name = String(n.color || "").toLowerCase();
    return NOTE_COLORS.indexOf(name) >= 0 ? name : "yellow";
  }

  /** At most two short lines of a node's own text, cut on a word where there is one. */
  function previewLines(n) {
    let text =
      n.type === "note" ? n.text || "" :
      n.type === "agent" ? n.prompt || "" :
      n.type === "condition" ? n.expression || "" :
      n.type === "approval" ? n.question || "" :
      n.type === "trigger" ? (n.trigger_mode || "") + (n.schedule ? " " + n.schedule : "") :
      (n.after || []).join(", ");
    text = String(text).replace(/\s+/g, " ").trim();
    const lines = [];
    while (text && lines.length < 2) {
      if (text.length <= 22) {
        lines.push(text);
        break;
      }
      let cut = text.lastIndexOf(" ", 22);
      if (cut < 8) cut = 22;
      lines.push(text.slice(0, cut).trim());
      text = text.slice(cut).trim();
    }
    if (text && lines.length === 2) lines[1] = lines[1].slice(0, 21) + "\u2026";
    return lines;
  }

  /** One node's last-run output as short canvas lines: strings verbatim, anything
   *  else as JSON, capped before wrapping so a digest cannot bury the canvas.
   *  Slicing is code-point based so emoji never splits into tofu. */
  function summarizeOutputs(result) {
    const out = {};
    const outputs = (result && result.outputs) || {};
    Object.keys(outputs).forEach((id) => {
      let text = outputs[id];
      text = typeof text === "string" ? text : JSON.stringify(text);
      text = String(text == null ? "" : text).replace(/\s+/g, " ").trim();
      const chars = Array.from(text);
      if (chars.length > 140) text = chars.slice(0, 139).join("") + "\u2026";
      if (text) out[id] = text;
    });
    return out;
  }

  /** Wrapped excerpt of one node's last output, or [] when there is nothing to show
   *  (no run yet, or the mounted run belongs to another design). */
  function outputLines(id) {
    if (!lastRunName || lastRunName !== graph.name) return [];
    const rest = lastOutputs[id] || "";
    if (!rest) return [];
    const lines = [];
    let chars = Array.from(rest);
    while (chars.length && lines.length < 2) {
      if (chars.length <= 22) { lines.push(chars.join("")); break; }
      let cut = chars.lastIndexOf(" ", 22);
      if (cut < 8) cut = 22;
      lines.push(chars.slice(0, cut).join("").trim());
      chars = chars.slice(cut);
      while (chars.length && chars[0] === " ") chars.shift();
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
  let fitLocked = false;

  function fit() {
    const svg = el.canvas;
    const avail = Math.max(240, (el.wrap.clientWidth || 0) - 12);
    let maxX = 0;
    let maxY = 0;
    graph.nodes.forEach((n) => {
      maxX = Math.max(maxX, n.x + NODE_W);
      maxY = Math.max(maxY, n.y + NODE_H);
    });
    let width = Math.max(maxX + 30, 320);
    const height = Math.max(maxY + 30, 200);
    let scale = avail / width;
    if (scale > 1) {
      width = avail;
      scale = 1;
    }
    svg.setAttribute("viewBox", "0 0 " + Math.round(width) + " " + Math.round(height));
    svg.setAttribute("width", Math.round(avail));
    svg.setAttribute("height", Math.round(Math.max(200, height * scale)));
    svg.setAttribute("preserveAspectRatio", "xMinYMin meet");
  }

  /** Re-fit when the window itself is resized (sidebars opening, window drag). */
  function watchSize() {
    if (typeof ResizeObserver !== "function") return;
    let width = el.wrap.clientWidth;
    sizeObserver = new ResizeObserver(() => {
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
      const g = svgEl("g", {
        transform: "translate(" + n.x + "," + n.y + ")",
        class: "vw-node",
        "data-id": n.id,
      });
      // SVG tooltips are a child <title>, not a title attribute.
      const tip = svgEl("title", {});
      tip.textContent = n.id + " \u00b7 " + (TIPS[n.type] || n.type);
      g.appendChild(tip);
      const isNote = n.type === NOTE;
      const box = {
        width: NODE_W, height: NODE_H, rx: 6,
        fill: isNote ? "var(--vw-note-" + noteColor(n) + ")" : "var(--vw-node)",
        stroke: isSelected ? "var(--vw-accent)" : "var(--vw-line)",
        "stroke-width": isSelected ? 2 : 1,
      };
      // A dashed edge is the cheapest "this is paper, not a step" cue that survives theming.
      if (isNote) box["stroke-dasharray"] = "5 3";
      g.appendChild(svgEl("rect", box));
      const kind = svgEl("text", { x: 9, y: 13, "font-size": 8, fill: "var(--vw-dim)" });
      kind.textContent = String(n.type).toUpperCase();
      const id = svgEl("text", { x: 9, y: 26, "font-size": 11, fill: "var(--vw-ink)" });
      id.textContent = n.id;
      g.appendChild(kind);
      g.appendChild(id);
      previewLines(n).forEach((text, line) => {
        const row = svgEl("text", {
          x: 9, y: 38 + line * 11, "font-size": 9, fill: "var(--vw-dim)",
        });
        row.textContent = text;
        g.appendChild(row);
      });
      outputLines(n.id).forEach((text, line) => {
        const out = svgEl("text", {
          x: 9, y: NODE_H + 12 + line * 11, "font-size": 9, fill: "var(--vw-dim)",
          class: "vw-output",
        });
        out.textContent = text;
        g.appendChild(out);
      });

      // A note has no ports at all: it takes no part in the graph, so there is nothing to
      // drag from and nothing to drop onto.
      if (n.type !== NOTE) {
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
      }

      wireNode(g, n);
      svg.appendChild(g);
    });
    if (!fitLocked) fit();
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
      fitLocked = true;
      const start = svgPoint(ev);
      const offset = { x: start.x - n.x, y: start.y - n.y };
      let moved = false;
      let frame = null;
      // One redraw per animation frame, not one per pixel: draw() rebuilds the whole SVG.
      function scheduleDraw() {
        if (frame) return;
        if (typeof requestAnimationFrame !== "function") { draw(); return; }
        frame = requestAnimationFrame(() => { frame = null; draw(); });
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
        const p = svgPoint(moveEv);
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
    fitLocked = true;
    dragLink = { from: n.id, x1: origin.x, y1: origin.y, x2: start.x, y2: start.y };
    draw();
    let frame = null;
    function scheduleDraw() {
      if (frame) return;
      if (typeof requestAnimationFrame !== "function") { draw(); return; }
      frame = requestAnimationFrame(() => { frame = null; draw(); });
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
      const p = svgPoint(moveEv);
      if (Math.abs(p.x - start.x) > 3 || Math.abs(p.y - start.y) > 3) moved = true;
      dragLink.x2 = p.x;
      dragLink.y2 = p.y;
      scheduleDraw();
    }
    function onUp(upEv) {
      cleanup();
      const from = dragLink.from;
      dragLink = null;
      fitLocked = false;
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
    gestureCleanup = cancel;
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    document.addEventListener("pointercancel", cancel);
    window.addEventListener("blur", cancel);
  }

  /** Add the *from* -> *to* edge, refusing the three ways it could be wrong. */
  function finishLink(from, to) {
    linkArm = null;
    const source = nodeById(from);
    const target = nodeById(to);
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
    const target = nodeById(to);
    if (target) {
      target.after = (target.after || []).filter((dep) => dep !== from);
    }
    selectedEdge = null;
    note("cut " + from + " \u2192 " + to);
    draw();
    buildInspector();
  }

  function removeSelected() {
    if (selectedEdge) {
      const pair = JSON.parse(selectedEdge);
      cutEdge(pair[0], pair[1]);
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
    linkArm = null;
    buildInspector();
    draw();
    note("removed " + removed);
  }

  /** A labelled inspector row. The tip rides on the label AND the control, so hovering
   *  either one explains it (a native title is the whole mechanism, here and in SVG). */
  function field(labelText, control, tip) {
    const wrap = document.createElement("div");
    const label = document.createElement("div");
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
    select.title = TIPS["agent.profile"];
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = profiles.length ? "\u2014 host default \u2014" : "\u2014 no profiles listed \u2014";
    blank.title = TIPS["agent.profile"];
    select.appendChild(blank);
    let known = false;
    profiles.forEach((p) => {
      const option = document.createElement("option");
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

  /** The host catalog as a grouped <select>: one optgroup per provider, because a step names
   *  exactly one model and the runtime derives its provider. Only the active provider's
   *  models are offered — anything else would fail loudly server-side. With no catalog,
   *  or an unknown active provider, the field stays typeable (fail open, never empty),
   *  and a saved model the catalog dropped stays selectable. */
  function modelSelect(current) {
    if (!models.length) {
      return textInput(current.model || "", (v) => {
        if (v) current.model = v;
        else delete current.model;
      }, "model id (optional)");
    }
    const offered = currentProvider
      ? models.filter((p) => p.slug === currentProvider)
      : models;
    const listed = offered.length ? offered : models;
    const select = document.createElement("select");
    select.title = TIPS["agent.model"];
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "\u2014 the bot's own model \u2014";
    blank.title = TIPS["agent.model"];
    select.appendChild(blank);
    let known = false;
    listed.forEach((p) => {
      const group = document.createElement("optgroup");
      group.label = p.label || p.slug;
      (p.models || []).forEach((id) => {
        const option = document.createElement("option");
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
      // A saved design can name a model this host no longer lists: keep it visible so opening
      // the inspector cannot silently retarget the step.
      const stale = document.createElement("option");
      stale.value = current.model;
      stale.textContent = current.model + " (not listed)";
      stale.selected = true;
      select.appendChild(stale);
    }
    select.addEventListener("change", () => {
      if (select.value) current.model = select.value;
      else delete current.model;
      draw();
    });
    return select;
  }

  /** Chats the host gateway has seen (``GET /channels``); empty means the canvas offers a
   *  free-text field instead of a picker that cannot fill. */
  /** One send-to value -> the two fields the backend reads. A bare platform is that
   *  platform's home channel (a notification); anything with a colon is one specific chat.
   *  Deriving both from one value is what makes the invalid pair impossible to build. */
  function applySendTo(node, value) {
    const target = String(value || "").trim();
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
    const select = document.createElement("select");
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "collect only \u2014 do not send";
    blank.title = TIPS["output.send_to"];
    select.appendChild(blank);
    const value = sendToValue(current);
    let known = false;
    channels.forEach((item) => {
      const option = document.createElement("option");
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
      const stale = document.createElement("option");
      stale.value = value;
      stale.textContent = value + " (not listed)";
      stale.title = TIPS["output.target"];
      stale.selected = true;
      select.appendChild(stale);
    }
    select.addEventListener("change", () => {
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
    const wrap = document.createElement("div");
    const preset = presetOf(node.schedule);
    const reading = document.createElement("p");

    const picker = document.createElement("select");
    PRESETS.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = PRESET_LABELS[name];
      option.title = TIPS["presets." + name];
      if (name === preset) option.selected = true;
      picker.appendChild(option);
    });
    picker.addEventListener("change", () => {
      if (picker.value !== "custom") {
        node.schedule = buildCron(picker.value, timeOf(node.schedule), weekdayOf(node.schedule));
      }
      buildInspector();
      draw();
    });
    wrap.appendChild(field("runs", picker, TIPS["trigger.preset"]));

    if (preset === "weekly") {
      const day = document.createElement("select");
      WEEKDAYS.forEach((pair) => {
        const option = document.createElement("option");
        option.value = pair[0];
        option.textContent = pair[1];
        option.title = TIPS["trigger.weekday"];
        if (pair[0] === weekdayOf(node.schedule)) option.selected = true;
        day.appendChild(option);
      });
      day.addEventListener("change", () => {
        node.schedule = buildCron(preset, timeOf(node.schedule), day.value);
        buildInspector();
        draw();
      });
      wrap.appendChild(field("day", day, TIPS["trigger.weekday"]));
    }

    // Shown for hourly too: buildCron takes the MINUTE from it, so hiding the field
    // silently pinned "every hour" to :00 with no way to choose :15.
    if (preset !== "custom") {
      const time = textInput(timeOf(node.schedule), (v) => {
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

    const cron = textInput(node.schedule || "", (v) => {
      node.schedule = v;
      draw();
      const problem = cronProblem(v);
      reading.className = problem ? "vw-error" : "vw-hint";
      reading.textContent = problem || describeCron(v);
    }, "0 9 * * 1-5");
    wrap.appendChild(field("cron (advanced)", cron, TIPS["trigger.schedule"]));

    const problem = cronProblem(node.schedule);
    reading.className = problem ? "vw-error" : "vw-hint";
    reading.textContent = problem || describeCron(node.schedule);
    reading.title = TIPS["trigger.schedule"];
    wrap.appendChild(reading);

    // A cron expression on the canvas is only a plan; say whether Hermes actually has the job.
    const statusLine = document.createElement("p");
    statusLine.className = "vw-hint";
    statusLine.title = TIPS["schedule.status"];
    statusLine.textContent = "Hermes cron: checking\u2026";
    wrap.appendChild(statusLine);
    const jobStatus = () => {
      const owner = currentName();
      if (!owner) {
        statusLine.className = "vw-hint";
        statusLine.textContent = "Hermes cron: save the workflow, then schedule it.";
        return;
      }
      call("/schedules").then((data) => {
        const jobs = (data && data.jobs) || [];
        const job = jobs.find((candidate) => (candidate.design || "") === owner);
        statusLine.className = "vw-hint";
        if (!data || !data.available) {
          statusLine.textContent = "Hermes cron: the scheduler could not be read here.";
        } else if (job) {
          statusLine.textContent = "Hermes cron: " + job.state +
            (job.next_run_at ? " \u00b7 next " + job.next_run_at : "") +
            "  (" + job.schedule + ")";
        } else {
          statusLine.textContent = "Hermes cron: not scheduled yet \u2014 press Schedule in Hermes.";
        }
      }).catch(() => {
        statusLine.textContent = "Hermes cron: could not be read.";
      });
    };
    jobStatus();

    const apply = button("Schedule in Hermes", () => {
      const name = currentName();
      if (!name) {
        reading.className = "vw-error";
        reading.textContent = "save the workflow first, then schedule it";
        return;
      }
      const issue = cronProblem(node.schedule);
      if (issue) {
        reading.className = "vw-error";
        reading.textContent = issue;
        return;
      }
      reading.className = "vw-hint";
      reading.textContent = "scheduling\u2026";
      call(designPath(name) + "/schedule", {
        method: "POST",
        // Same shape as the Schedules form, so the two call sites cannot drift.
        body: {
          preset: presetOf(node.schedule),
          time: timeOf(node.schedule),
          weekday: weekdayOf(node.schedule),
          cron: node.schedule,
        },
      }).then((data) => {
        if (!data || !data.ok) {
          reading.className = "vw-error";
          reading.textContent = (data && data.error) || "the scheduler refused it";
          return;
        }
        reading.className = "vw-hint";
        reading.textContent = (data.created ? "scheduled \u00b7 " : "updated \u00b7 ") +
          describeCron(data.cron || node.schedule);
        refreshDesigns();
        jobStatus();
      }).catch((err) => {
        reading.className = "vw-error";
        reading.textContent = explain(err);
      });
    });
    apply.title = TIPS["schedule.save"];
    wrap.appendChild(apply);
    return wrap;
  }

  function buildInspector() {
    const box = el.inspector;
    box.textContent = "";
    const current = selected ? nodeById(selected) : null;
    if (!current) {
      setInspector(false);
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

    if (current.type === NOTE) {
      box.appendChild(field("note text", textArea(current.text || "", (v) => {
        current.text = v;
        draw();
      }, 3), TIPS["note.text"]));
      const tint = document.createElement("select");
      tint.title = TIPS["note.color"];
      NOTE_COLORS.forEach((name) => {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        option.title = TIPS["note.color"];
        if (noteColor(current) === name) option.selected = true;
        tint.appendChild(option);
      });
      tint.addEventListener("change", () => {
        current.color = tint.value;
        draw();
      });
      box.appendChild(field("colour", tint, TIPS["note.color"]));
      // Say the one thing a note is easy to be mistaken for: a step.
      const why = document.createElement("p");
      why.className = "vw-hint";
      why.title = TIPS["note"];
      why.textContent = "A note is for people reading the canvas; it never runs.";
      box.appendChild(why);
    } else if (current.type === "trigger") {
      const select = document.createElement("select");
      select.title = TIPS["trigger.trigger_mode"];
      MODES.forEach((mode) => {
        const option = document.createElement("option");
        option.value = mode;
        option.textContent = mode;
        option.title = TIPS["trigger.trigger_mode"];
        if (current.trigger_mode === mode) option.selected = true;
        select.appendChild(option);
      });
      select.addEventListener("change", () => {
        current.trigger_mode = select.value;
        buildInspector();
        draw();
      });
      box.appendChild(field("trigger_mode", select, TIPS["trigger.trigger_mode"]));
      if (current.trigger_mode === "schedule") {
        box.appendChild(scheduleFields(current));
      }
    } else if (current.type === "agent") {
      box.appendChild(field("prompt", textArea(current.prompt || "", (v) => {
        current.prompt = v;
        draw();
      }, 5), TIPS["agent.prompt"]));
      box.appendChild(field("profile / bot (optional)", profileSelect(current), TIPS["agent.profile"]));
      const chosen = profileByName(current.profile);
      if (chosen) {
        const runs = document.createElement("p");
        runs.className = "vw-hint";
        runs.textContent = "runs as " + (chosen.label || chosen.name) +
          (chosen.model ? " \u00b7 " + chosen.model : "");
        box.appendChild(runs);
      }
      box.appendChild(field("model (optional)", modelSelect(current), TIPS["agent.model"]));
      box.appendChild(field("retries (optional)", textInput(
        current.retries ? String(current.retries) : "",
        (v) => {
          const count = parseInt(v, 10);
          if (!v.trim() || isNaN(count) || count <= 0) delete current.retries;
          else current.retries = Math.min(3, count);
          draw();
        },
        "0"
      ), TIPS["agent.retries"]));
    } else if (current.type === "condition") {
      box.appendChild(field("expression", textInput(current.expression || "", (v) => {
        current.expression = v;
        draw();
      }, "out.draft.word_count > 20"), TIPS["condition.expression"]));
      const hint = document.createElement("p");
      hint.className = "vw-hint";
      hint.textContent = "Must start with out.<node>.<field> <op> <value>.";
      box.appendChild(hint);
    } else if (current.type === "approval") {
      box.appendChild(field("question", textArea(current.question || "", (v) => {
        current.question = v;
        draw();
      }, 3), TIPS["approval.question"]));
      box.appendChild(field("context (optional)", textArea(current.context || "", (v) => {
        if (v.trim()) current.context = v;
        else delete current.context;
        draw();
      }, 3), TIPS["approval.context"]));
      box.appendChild(field("options (comma separated)", textInput(
        (current.options || []).join(", "),
        (v) => {
          const list = v.split(",").map((s) => s.trim()).filter(Boolean);
          if (list.length) current.options = list;
          else delete current.options;
          draw();
        },
        "ship, edit"
      ), TIPS["approval.options"]));
      box.appendChild(field("timeout (minutes, optional)", textInput(
        current.timeout_minutes ? String(current.timeout_minutes) : "",
        (v) => {
          const minutes = parseInt(v, 10);
          if (!v.trim() || isNaN(minutes) || minutes <= 0) delete current.timeout_minutes;
          else current.timeout_minutes = minutes;
          draw();
        },
        "60"
      ), TIPS["approval.timeout"]));
      const policy = document.createElement("select");
      policy.title = TIPS["approval.on_timeout"];
      [["reject", "reject \u2014 fail the run"],
       ["escalate", "escalate \u2014 flag it for someone else"]].forEach((pair) => {
        const option = document.createElement("option");
        option.value = pair[0];
        option.textContent = pair[1];
        option.title = TIPS["approval.on_timeout"];
        if ((current.on_timeout || "reject") === pair[0]) option.selected = true;
        policy.appendChild(option);
      });
      policy.addEventListener("change", () => {
        current.on_timeout = policy.value;
        draw();
      });
      box.appendChild(field("if it times out", policy, TIPS["approval.on_timeout"]));
    } else if (current.type === "output") {
      const parents = document.createElement("p");
      parents.className = "vw-muted";
      parents.textContent = (current.after || []).length
        ? (current.after || []).join(", ")
        : "(no parents \u2014 this output collects nothing)";
      box.appendChild(field("parents", parents, TIPS["output.parents"]));
      if (channels.length) {
        box.appendChild(field("send to", sendToSelect(current), TIPS["output.send_to"]));
      } else {
        box.appendChild(field("send to", textInput(current.target || "", (v) => {
          applySendTo(current, v);
          draw();
        }, "telegram:8522302999"), TIPS["output.target"]));
      }
      const targetHint = document.createElement("p");
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
    const box = el.banner;
    box.textContent = "";
    if (!message) {
      box.hidden = true;
      box.className = "vw-banner";
      return;
    }
    box.hidden = false;
    box.className = "vw-banner vw-banner-" + (kind || "info");
    const text = document.createElement("p");
    text.textContent = message;
    box.appendChild(text);
    const close = document.createElement("button");
    close.type = "button";
    close.className = "vw-pill";
    close.textContent = "\u2715";
    close.title = "Dismiss this message.";
    close.setAttribute("aria-label", "Dismiss message");
    close.addEventListener("click", () => banner(""));
    box.appendChild(close);
  }

  /** Validation problems go to the canvas banner AND the detail box; never a silent word. */
  function showErrors(errors) {
    const list = errors || [];
    if (!list.length) {
      el.errors.textContent = "";
      el.errors.hidden = true;
      return;
    }
    el.errors.hidden = false;
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
    if (kind === "note") fresh.text = "";
    if (typeof x === "number" && typeof y === "number") {
      fresh.x = Math.max(0, Math.round(x - NODE_W / 2));
      fresh.y = Math.max(0, Math.round(y - NODE_H / 2));
    } else {
      const slot = graph.nodes.length;
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

  function renderDesigns() {
    const box = el.designs;
    box.textContent = "";
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = designs.length ? "\u2014 saved workflows \u2014" : "no saved workflows yet";
    box.appendChild(blank);
    designs.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      box.appendChild(option);
    });
    box.value = active && designs.indexOf(active) >= 0 ? active : "";
  }

  /** Profiles ("bots") for the agent picker. A failure is not fatal: the picker just offers
   *  nothing and the model field stays typeable. */
  /** Rebuild the drawer only when the user is not typing in it: a catalog response landing
   *  mid-edit must not wipe the control and its cursor. */
  function refreshInspector() {
    if (!el.inspector.contains(document.activeElement)) buildInspector();
  }

  function refreshProfiles() {
    return call("/profiles").then((data) => {
      profiles = (data && data.profiles) || [];
      refreshInspector();
    }).catch(() => {
      profiles = [];
    });
  }

  /** The host catalog behind the model dropdown. A failure is not fatal either: an empty list
   *  leaves the agent node's model field a free-text input. */
  function refreshModels() {
    return call("/models").then((data) => {
      models = (data && data.providers) || [];
      currentProvider = (data && data.current && data.current["provider"]) || "";
      refreshInspector();
    }).catch(() => {
      models = [];
      currentProvider = "";
    });
  }

  /** Delivery targets ("chats") for the output picker. A failure is not fatal either: the
   *  node keeps its free-text target field. */
  function refreshChannels() {
    return call("/channels").then((data) => {
      channels = (data && data.channels) || [];
      refreshInspector();
    }).catch(() => {
      channels = [];
    });
  }

  // ------------------------------------------------------------ schedules view
  // The Schedules view is one page with the designer (the host allows one route per plugin):
  // a rail switch swaps the canvas for the cron jobs this plugin created.
  let view = "designer";
  let schedName = "";
  let schedPreset = "daily";
  let schedTime = "09:00";
  let schedDay = "mon";
  let schedCron = "";

  function showView(next) {
    view = next === "schedules" || next === "runs" ? next : "designer";
    el.app.hidden = view !== "designer";
    el.sched.hidden = view !== "schedules";
    el.runs.hidden = view !== "runs";
    ["designer", "runs", "schedules"].forEach(function (name) {
      q('[data-vw="view-' + name + '"]').setAttribute(
        "aria-pressed", view === name ? "true" : "false");
    });
    if (view === "schedules") renderSchedules();
    if (view === "runs") renderRuns();
    if (view === "designer") fit();
  }

  /** "3m ago" — a waiting gate has to say how long it has waited. */
  function ageText(timestamp) {
    // Accept epoch seconds, milliseconds and ISO strings; an unknown value says so instead
    // of rendering "NaN d ago".
    let when = typeof timestamp === "string"
      ? Date.parse(timestamp) / 1000
      : Number(timestamp || 0);
    if (!Number.isFinite(when) || when <= 0) return "unknown age";
    if (when > 1e11) when /= 1000;
    const age = Math.max(0, Math.round(Date.now() / 1000 - when));
    if (age < 60) return age + "s ago";
    if (age < 3600) return Math.round(age / 60) + "m ago";
    if (age < 86400) return Math.round(age / 3600) + "h ago";
    return Math.round(age / 86400) + "d ago";
  }

  /**
   * Every run saved on disk, newest first \u2014 including runs the chat tool or a cron job
   * started, which this page used to be unable to see or answer.
   */
  function renderRuns() {
    call("/runs?limit=20").then((data) => {
      const runs = (data && data.runs) || [];
      const box = el.runs;
      box.textContent = "";
      const title = document.createElement("p");
      title.className = "vw-rail-title";
      title.textContent = "Runs";
      box.appendChild(title);
      const hint = document.createElement("p");
      hint.className = "vw-hint";
      hint.textContent = "Every run saved on this machine, newest first \u2014 including runs " +
        "started in chat or by a schedule.";
      box.appendChild(hint);
      if (!runs.length) {
        const empty = document.createElement("p");
        empty.className = "vw-muted";
        empty.textContent = "No runs yet.";
        box.appendChild(empty);
      }
      runs.forEach((run) => box.appendChild(runRow(run)));
      const refresh = button("Refresh", () => renderRuns());
      refresh.title = TIPS["runs.refresh"];
      box.appendChild(refresh);
    }).catch((err) => {
      el.railError.textContent = explain(err);
    });
  }

  function retryStoredRun(run) {
    call("/runs/" + encodeURIComponent(run.run_id) + "/retry", {
      method: "POST",
      body: {},
    }).then((data) => {
      el.railError.textContent = "";
      note(run.run_id + ": " + ((data && data.status) || "no status"));
      renderRuns();
    }).catch((err) => {
      el.railError.textContent = explain(err);
    });
  }

  function answerRun(run, option) {
    call("/runs/" + encodeURIComponent(run.run_id) + "/respond", {
      method: "POST",
      body: { run_id: run.run_id, node_id: run.node_id, answer: option },
    }).then((data) => {
      el.railError.textContent = "";
      note(run.run_id + ": " + ((data && data.status) || "no status"));
      renderRuns();
    }).catch((err) => {
      el.railError.textContent = explain(err);
    });
  }

  /** Bring a stored run into the designer's run panel, where its resume box is mounted. */
  function openRun(run) {
    if (!run || !run.name) return;
    call("/designs/" + encodeURIComponent(run.name)).then((data) => {
      loadGraph(data.graph);
      renderDesigns();
      showView("designer");
      return call("/runs/" + encodeURIComponent(run.run_id));
    }).then((state) => {
      if (state) renderRun(state);
    }).catch((err) => {
      el.railError.textContent = explain(err);
    });
  }

  // A finished run's text lives only on disk; mount it without disturbing the canvas:
  // no design load, so a renamed or deleted design cannot hide a stored result.
  function showStoredRun(run) {
    if (!run || !run.run_id) return;
    showView("designer");
    call("/runs/" + encodeURIComponent(run.run_id)).then((state) => {
      if (state) renderRun(state);
    }).catch((err) => {
      el.railError.textContent = explain(err);
    });
  }

  function runRow(run) {
    const row = document.createElement("div");
    row.className = "vw-job";
    const head = document.createElement("div");
    head.className = "vw-job-head";
    const name = document.createElement("strong");
    name.textContent = run.name || "(unnamed)";
    const meta = document.createElement("span");
    meta.className = "vw-muted";
    meta.textContent = " \u00b7 " + run.status + " \u00b7 " + run.run_id + " \u00b7 " +
      ageText(run.updated);
    head.appendChild(name);
    head.appendChild(meta);
    row.appendChild(head);

    const isGate = run.status === "awaiting_approval";
    if (isGate) {
      const question = document.createElement("p");
      question.className = "vw-hint";
      question.textContent = "gate " + run.node_id + ": " + (run.question || "");
      row.appendChild(question);
      const deadline = waitText(run);
      if (deadline) {
        const wait = document.createElement("p");
        wait.className = "vw-hint";
        wait.title = TIPS["approval.timeout"];
        wait.textContent = deadline;
        row.appendChild(wait);
      }
      if (!(run.options || []).length) {
        const free = document.createElement("p");
        free.className = "vw-hint";
        free.textContent = "This gate takes free text \u2014 answer it in chat.";
        row.appendChild(free);
      }
    }
    if (run.status === "awaiting_agent") {
      const waiting = document.createElement("p");
      waiting.className = "vw-hint";
      waiting.textContent = "agent step " + run.node_id + " is paused \u2014 open the run to paste " +
        "its result, or answer it from chat.";
      row.appendChild(waiting);
      const answer = document.createElement("button");
      answer.type = "button";
      answer.className = "vw-pill";
      answer.textContent = "Answer";
      answer.title = TIPS["runs.resume"];
      answer.addEventListener("click", () => openRun(run));
      row.appendChild(answer);
    }
    if (run.error) {
      const failed = document.createElement("p");
      failed.className = "vw-error";
      failed.textContent = (run.error.node_id ? run.error.node_id + ": " : "") +
        (run.error.msg || "");
      row.appendChild(failed);
      // A diagnosed failure gets a labelled chip in the row, the hint rides its title.
      if (run.error.kind) {
        const chip = document.createElement("span");
        chip.className = "vw-chip";
        chip.textContent = run.error.kind;
        chip.title = run.error.hint || "diagnosed failure kind";
        row.appendChild(chip);
      }
    }
    if ((run.deliveries || []).length) {
      const sent = document.createElement("p");
      sent.className = "vw-hint";
      sent.textContent = "delivery: " + run.deliveries.map((d) => {
        return (d.ok ? "sent " : "FAILED ") + d.node_id + " \u2192 " + (d.target || "?");
      }).join(" \u00b7 ");
      row.appendChild(sent);
    }

    const actions = document.createElement("div");
    actions.className = "vw-job-actions";
    if (isGate) {
      (run.options || []).forEach((option) => {
        const pick = button(option, () => answerRun(run, option));
        pick.title = TIPS["runs.approve"];
        actions.appendChild(pick);
      });
    }
    if (run.status === "failed") {
      const retry = button("Retry", () => retryStoredRun(run));
      retry.title = TIPS["runs.retry"];
      actions.appendChild(retry);
    }
    if (run.status === "done") {
      // Mounts the stored result only — unlike Open, a renamed or deleted design
      // cannot hide a finished run's outputs.
      const result = button("Result", () => showStoredRun(run));
      result.title = TIPS["runs.result"];
      actions.appendChild(result);
    }
    if (run.name) {
      const reopen = button("Open", () => {
        open(run.name);
        showView("designer");
      });
      reopen.title = TIPS["runs.open"];
      actions.appendChild(reopen);
    }
    row.appendChild(actions);
    return row;
  }

  function scheduleAct(job, action) {
    el.railError.textContent = "";
    call("/schedules/" + encodeURIComponent(job.job_id) + "/" + action, { method: "POST" })
      .then((data) => {
        if (!data || !data.ok) {
          el.railError.textContent = (data && data.error) || "the scheduler refused it";
          return;
        }
        note(action + " \u00b7 " + (job.design || job.name));
        renderSchedules();
      }).catch((err) => {
        el.railError.textContent = explain(err);
      });
  }

  function jobRow(job) {
    const row = document.createElement("div");
    row.className = "vw-job";
    const head = document.createElement("div");
    head.className = "vw-job-head";
    const name = document.createElement("strong");
    name.textContent = job.design || job.name;
    const meta = document.createElement("span");
    meta.className = "vw-muted";
    meta.textContent = " \u00b7 " + job.state + (job.next_run_at ? " \u00b7 next " + job.next_run_at : "");
    head.appendChild(name);
    head.appendChild(meta);
    row.appendChild(head);
    const when = document.createElement("p");
    when.className = "vw-hint";
    when.textContent = describeCron(job.schedule) + "  (" + job.schedule + ")";
    when.title = TIPS["trigger.schedule"];
    row.appendChild(when);
    const actions = document.createElement("div");
    actions.className = "vw-job-actions";
    const pause = button("Pause", () => scheduleAct(job, "pause"));
    pause.title = TIPS["schedules.pause"];
    pause.disabled = job.state === "paused";
    const resume = button("Resume", () => scheduleAct(job, "resume"));
    resume.title = TIPS["schedules.resume"];
    resume.disabled = job.state !== "paused";
    const run = button("Run now", () => scheduleAct(job, "run"));
    run.title = TIPS["schedules.run"];
    const remove = button("Delete", () => scheduleAct(job, "remove"));
    remove.title = TIPS["schedules.remove"];
    [pause, resume, run, remove].forEach((b) => actions.appendChild(b));
    row.appendChild(actions);
    return row;
  }

  /** Pick a saved workflow, pick a schedule in plain words, create the cron job. */
  function scheduleForm() {
    const form = document.createElement("div");
    form.className = "vw-sched-form";

    const pick = document.createElement("select");
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "\u2014 pick a saved workflow \u2014";
    pick.appendChild(blank);
    designs.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      if (name === schedName) option.selected = true;
      pick.appendChild(option);
    });
    pick.addEventListener("change", () => {
      schedName = pick.value;
    });
    form.appendChild(field("workflow", pick, TIPS["bar.name"]));

    // One reading, recomputed from the live picker state. Computing it once at render and
    // closing over it made "change the time, press Schedule" submit the old expression.
    const reading = document.createElement("p");
    reading.title = TIPS["trigger.schedule"];
    function currentExpression() {
      return buildCron(schedPreset, schedTime, schedDay, schedCron);
    }
    function refreshReading() {
      const expression = currentExpression();
      const problem = cronProblem(expression);
      reading.className = problem ? "vw-error" : "vw-hint";
      reading.textContent = problem ? "" : describeCron(expression) + "  (" + expression + ")";
      return expression;
    }

    const presetSelect = document.createElement("select");
    PRESETS.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = PRESET_LABELS[name];
      option.title = TIPS["presets." + name];
      if (name === schedPreset) option.selected = true;
      presetSelect.appendChild(option);
    });
    presetSelect.addEventListener("change", () => {
      schedPreset = presetSelect.value;
      renderSchedules();
    });
    form.appendChild(field("runs", presetSelect, TIPS["trigger.preset"]));

    if (schedPreset === "weekly") {
      const day = document.createElement("select");
      WEEKDAYS.forEach((pair) => {
        const option = document.createElement("option");
        option.value = pair[0];
        option.textContent = pair[1];
        option.title = TIPS["trigger.weekday"];
        if (pair[0] === schedDay) option.selected = true;
        day.appendChild(option);
      });
      day.addEventListener("change", () => {
        schedDay = day.value;
        refreshReading();
      });
      form.appendChild(field("day", day, TIPS["trigger.weekday"]));
    }

    // Hourly keeps the field: only its minute survives into the cron expression.
    if (schedPreset !== "custom") {
      const time = textInput(schedTime, (v) => {
        schedTime = v;
        refreshReading();
      }, "09:00");
      form.appendChild(field("time (24h)", time, TIPS["trigger.time"]));
    }

    if (schedPreset === "custom") {
      const cron = textInput(schedCron, (v) => {
        schedCron = v;
        refreshReading();
      }, "0 9 * * 1-5");
      form.appendChild(field("cron (advanced)", cron, TIPS["trigger.schedule"]));
    }

    refreshReading();
    form.appendChild(reading);

    const go = button("Schedule it", () => {
      if (!schedName) {
        reading.className = "vw-error";
        reading.textContent = "pick a workflow first";
        return;
      }
      // Rebuild from the live fields: the rendering-time expression may be stale.
      const expression = refreshReading();
      const issue = cronProblem(expression);
      if (issue) {
        reading.className = "vw-error";
        reading.textContent = issue;
        return;
      }
      reading.className = "vw-hint";
      reading.textContent = "scheduling\u2026";
      call(designPath(schedName) + "/schedule", {
        method: "POST",
        body: { preset: schedPreset, time: schedTime, weekday: schedDay, cron: expression },
      }).then((data) => {
        if (!data || !data.ok) {
          reading.className = "vw-error";
          reading.textContent = (data && data.error) || "the scheduler refused it";
          return;
        }
        reading.className = "vw-hint";
        reading.textContent = (data.created ? "scheduled " : "updated ") + schedName +
          " \u00b7 " + describeCron(data.cron || expression);
        renderSchedules();
        refreshDesigns();
      }).catch((err) => {
        reading.className = "vw-error";
        reading.textContent = explain(err);
      });
    });
    go.title = TIPS["schedules.create"];
    form.appendChild(go);
    return form;
  }

  function renderSchedules() {
    call("/schedules").then((data) => {
      const jobs = (data && data.jobs) || [];
      const box = el.sched;
      box.textContent = "";
      const title = document.createElement("p");
      title.className = "vw-rail-title";
      title.textContent = "Scheduled runs";
      box.appendChild(title);
      if (!data || !data.available) {
        const offline = document.createElement("p");
        offline.className = "vw-error";
        offline.textContent = "The host scheduler could not be read here \u2014 nothing is listed.";
        box.appendChild(offline);
      }
      if (!jobs.length) {
        const empty = document.createElement("p");
        empty.className = "vw-muted";
        empty.textContent = "No scheduled workflows yet.";
        box.appendChild(empty);
      }
      jobs.forEach((job) => box.appendChild(jobRow(job)));
      box.appendChild(scheduleForm());
    }).catch((err) => {
      el.railError.textContent = explain(err);
    });
  }

  function refreshDesigns() {
    return call("/designs").then((data) => {
      designs = (data && data.designs) || [];
      // Run needs to know which names exist server-side, so a draft is refused with a
      // sentence instead of a 404 nobody sees.
      savedNames = designs.slice();
      designsLoaded = true;
      el.railError.textContent = "";
      renderDesigns();
    }).catch((err) => {
      // Leave designsLoaded alone: an initial failure means Run must not gate on an
      // empty cache (the POST will return the authoritative 404).
      el.railError.textContent = explain(err);
    });
  }

  /** Built-ins ship with the plugin; an empty list means an older copy, not a broken tab. */
  function refreshTemplates() {
    return call("/designs/templates").then((data) => {
      templates = (data && data.templates) || [];
      renderTemplates();
    }).catch(() => {
      templates = [];
      renderTemplates();
    });
  }

  function renderTemplates() {
    const box = el.templates;
    box.textContent = "";
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = templates.length
      ? "\u2014 start from a template \u2014"
      : "no templates";
    box.appendChild(blank);
    templates.forEach((row) => {
      const option = document.createElement("option");
      option.value = row.name;
      option.textContent = row.title;
      option.title = row.description;
      box.appendChild(option);
    });
    box.disabled = !templates.length;
    box.value = "";
  }

  // A template is a draft, not a saved design: load it onto the canvas and let the user save it
  // under their own name.
  function useTemplate(name) {
    const row = templates.filter((t) => t.name === name)[0];
    if (!row) return;
    active = "";
    el.railError.textContent = "";
    loadGraph(clone(row.graph));
    renderDesigns();
  }

  function open(name) {
    call(designPath(name)).then((data) => {
      active = name;
      el.railError.textContent = "";
      loadGraph(data.graph);
      renderDesigns();
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
      if (data.valid) {
        note("valid");
        banner("Design is valid \u00b7 " + graph.nodes.length + " node(s).", "info");
      } else {
        note((data.errors || []).length + " problem(s)");
        banner("Not valid \u00b7 " + (data.errors || []).length + " problem(s) \u2014 see the details below the canvas.", "error");
      }
    }).catch((err) => {
      note("");
      showErrors([{ node: "", field: "request", msg: explain(err) }]);
      banner("Validate failed \u2014 " + explain(err), "error");
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
        banner("Not saved \u2014 " + (data.errors || []).length + " problem(s), see the details below the canvas.", "error");
        return;
      }
      active = name;
      // A refresh is async; remember this name now so pressing Run immediately after Save
      // cannot be refused as "not saved yet".
      if (savedNames.indexOf(data.name) < 0) savedNames.push(data.name);
      showErrors([]);
      note("saved " + data.name + " (" + data.nodes + " node(s))");
      banner("Saved \u201c" + data.name + "\u201d \u00b7 " + data.nodes + " node(s).", "info");
      refreshDesigns();
    }).catch((err) => {
      note("");
      showErrors([{ node: "", field: "save", msg: explain(err) }]);
      banner("Save failed \u2014 " + explain(err), "error");
    });
  }

  function runDesign() {
    const name = currentName();
    if (!name) {
      showErrors([{ node: "", field: "name", msg: "save the design first" }]);
      banner("Name the design and press Save before running it.", "error");
      return;
    }
    // A draft that was never saved has no server-side design to run: saying so beats a 404.
    // Only gate once the list has actually loaded; before that the POST is authoritative.
    if (designsLoaded && !savedNames.includes(name)) {
      showErrors([{ node: "", field: "name", msg: name + " is not saved yet" }]);
      note("not run");
      banner("\u201c" + name + "\u201d is not saved yet \u2014 press Save, then Run.", "error");
      return;
    }
    note("running " + name + "\u2026");
    banner("Running \u201c" + name + "\u201d\u2026", "info");
    call(designPath(name) + "/run", { method: "POST" }).then((data) => {
      if (data.status === "invalid") {
        showErrors(data.errors || []);
        note("not run");
        banner("Not run \u2014 the design has " + (data.errors || []).length + " problem(s).", "error");
        return;
      }
      showErrors([]);
      renderRun(data);
    }).catch((err) => {
      note("");
      showErrors([{ node: "", field: "run", msg: explain(err) }]);
      banner("Run failed \u2014 " + explain(err), "error");
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
      banner("Could not resume the run \u2014 " + explain(err), "error");
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
    call("/runs/" + encodeURIComponent(lastRun.run_id) + "/respond", {
      method: "POST",
      body: { run_id: lastRun.run_id, node_id: nodeId, agent_generate: true },
    }).then((data) => {
      showErrors([]);
      renderRun(data);
    }).catch((err) => {
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
    call("/runs/" + encodeURIComponent(lastRun.run_id) + "/retry", {
      method: "POST",
      body: {},
    }).then((data) => {
      showErrors([]);
      renderRun(data);
    }).catch((err) => {
      note("");
      el.run.textContent = explain(err);
      banner("Could not retry the run \u2014 " + explain(err), "error");
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

  /** "waiting 12m \u00b7 expires in 48m" for a timed gate; "" when it has no deadline. */
  function waitText(pending) {
    if (!pending || !pending.timeout_minutes) return "";
    const since = Number(pending.waiting_since || 0) * 1000;
    if (!since) return "";
    const left = Number(pending.timeout_minutes) * 60000 - (Date.now() - since);
    const span = (ms) => {
      const minutes = Math.max(0, Math.round(ms / 60000));
      return minutes >= 60 ? Math.round(minutes / 60) + "h" : minutes + "m";
    };
    return left > 0
      ? "waiting " + span(Date.now() - since) + " \u00b7 expires in " + span(left)
      : "past its " + pending.timeout_minutes + "-minute deadline";
  }

  function waitLine(pending) {
    const text = waitText(pending);
    if (!text) return null;
    const node = line("p", text, "vw-hint");
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
    const box = el.run;
    box.textContent = "";
    const status = result.status;
    note(String(status || ""));
    // The run box lives under the canvas where it can be scrolled out of sight; bring it in.
    if (box.scrollIntoView) box.scrollIntoView({ block: "nearest" });

    if (status === "awaiting_approval") {
      const pending = result.pending || {};
      banner("Run " + (result.run_id || "") + " paused at gate " + pending.node_id + " \u2014 answer it below.", "warn");
      box.appendChild(line("h4", "gate " + pending.node_id + ": " + (pending.question || "")));
      if (pending.context) box.appendChild(line("pre", pending.context));
      const wait = waitLine(pending);
      if (wait) box.appendChild(wait);
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
      const agentRun = button("Run this step with the agent", () => {
        respondByAgent(step.node_id);
      });
      agentRun.title = TIPS["runs.agent"];
      box.appendChild(agentRun);
      box.appendChild(line("p", "Or paste the step's result here and press resume \u2014 no chat needed.", "vw-hint"));
      const area = document.createElement("textarea");
      area.rows = 3;
      area.placeholder = "paste the step's output (a JSON object is passed as structured)";
      area.setAttribute("aria-label", "result for agent step " + step.node_id);
      box.appendChild(area);
      const send = button("Send result & resume", () => {
        respond(step.node_id, area.value);
      });
      send.title = TIPS["runs.resume"];
      box.appendChild(send);
      box.appendChild(line("p", "Or run the workflow from chat and the agent executes the step for you.", "vw-hint"));
      return;
    }

    if (status === "failed") {
      const error = result.error || {};
      banner("Run " + (result.run_id || "") + " failed \u2014 " + (error.node_id ? error.node_id + ": " : "") + (error.msg || ""), "error");
      box.appendChild(line("h4", "run failed"));
      box.appendChild(line("pre", (error.node_id ? error.node_id + ": " : "") + (error.msg || "")));
      // A diagnosed failure gets a labelled chip; the hint is the chip's tooltip and the
      // raw message above stays the evidence. No diagnosis, no chip — as before.
      if (error.kind) {
        const chip = line("span", error.kind, "vw-chip");
        chip.title = error.hint || "diagnosed failure kind";
        box.appendChild(chip);
      }
      const retryRun = button("Retry run", () => retryFailedRun());
      retryRun.title = TIPS["runs.retry"];
      box.appendChild(retryRun);
      const failedDelivery = deliveryLine(result);
      if (failedDelivery) box.appendChild(failedDelivery);
      return;
    }

    if (status === "done") {
      const outputs = result.outputs || {};
      banner("Run " + (result.run_id || "") + " finished \u00b7 outputs: " + (Object.keys(outputs).join(", ") || "(none)"), "info");
      box.appendChild(line("h4", "done \u00b7 outputs: " + (Object.keys(outputs).join(", ") || "(none)")));
      if ((result.skipped || []).length) {
        box.appendChild(line("p", "skipped: " + result.skipped.join(", "), "vw-muted"));
      }
      const delivered = deliveryLine(result);
      if (delivered) box.appendChild(delivered);
      box.appendChild(line("pre", JSON.stringify(outputs, null, 2)));
      return;
    }

    banner("Run " + (result.run_id || "") + " \u00b7 " + String(status || "unknown"), "warn");
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
    el.name.title = TIPS["bar.name"];
    q('[data-vw="validate"]').title = TIPS["bar.validate"];
    q('[data-vw="save"]').title = TIPS["bar.save"];
    q('[data-vw="run-now"]').title = TIPS["bar.run"];
    q('[data-vw="delete"]').title = TIPS["bar.delete"];
    q('[data-vw="view-designer"]').title = "Edit the workflow on the canvas.";
    q('[data-vw="view-runs"]').title = "Every run saved on this machine, with any waiting gate answerable here.";
    q('[data-vw="view-schedules"]').title = "See and control the Hermes cron jobs this plugin created.";
    q('[data-vw="view-designer"]').addEventListener("click", () => showView("designer"));
    q('[data-vw="view-runs"]').addEventListener("click", () => showView("runs"));
    q('[data-vw="view-schedules"]').addEventListener("click", () => showView("schedules"));
    q('[data-vw="validate"]').addEventListener("click", validateDraft);
    q('[data-vw="save"]').addEventListener("click", saveDesign);
    q('[data-vw="run-now"]').addEventListener("click", runDesign);
    q('[data-vw="delete"]').addEventListener("click", removeSelected);
    q('[data-vw="insp-toggle"]').addEventListener("click", () => {
      setInspector(el.app.classList.contains("vw-insp-collapsed"));
    });
    el.designs.title = "Open a saved workflow, or keep the draft on the canvas.";
    el.designs.addEventListener("change", () => {
      if (el.designs.value) open(el.designs.value);
    });
    el.templates.title = TIPS["bar.templates"];
    el.templates.addEventListener("change", () => {
      if (el.templates.value) useTemplate(el.templates.value);
    });
    q('[data-vw="new"]').title = TIPS["bar.new"];
    q('[data-vw="new"]').addEventListener("click", () => {
      active = "";
      el.railError.textContent = "";
      loadGraph(Object.assign(clone(BLANK), { name: "untitled" }));
      renderDesigns();
    });

    Array.prototype.forEach.call(host.querySelectorAll("[data-kind]"), (b) => {
      const kind = b.getAttribute("data-kind");
      b.title = TIPS[kind] || kind;
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
      if (PALETTE.indexOf(kind) < 0) return;
      const p = svgPoint(ev);
      addNode(kind, p.x, p.y);
    });
  }

  /** Replace the canvas with a stored graph (or a blank one). */
  function loadGraph(next) {
    // A saved design / template is untrusted input: a non-list `nodes` used to reach
    // layout() and throw, leaving a blank canvas with no explanation.
    const usable = next && typeof next === "object" && Array.isArray(next.nodes)
      && next.nodes.length;
    graph = clone(usable ? next : BLANK);
    graph.nodes = graph.nodes.filter((n) => n && typeof n === "object"
      && typeof n.id === "string" && n.id);
    graph.nodes.forEach((n) => {
      n.after = Array.isArray(n.after) ? n.after.filter((dep) => typeof dep === "string") : [];
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

  wire();
  watchSize();
  layout();
  el.name.value = graph.name;
  showView("designer");
  buildInspector();
  draw();
  renderDesigns();
  renderTemplates();
  refreshDesigns();
  refreshTemplates();
  refreshProfiles();
  refreshModels();
  refreshChannels();

  /** Release what the mount owns: the size observer and any in-flight drag listeners. */
  function destroy() {
    if (gestureCleanup) gestureCleanup();
    if (sizeObserver) {
      sizeObserver.disconnect();
      sizeObserver = null;
    }
    el.inspector.textContent = "";
  }

  return { loadGraph: loadGraph, getGraph: payloadGraph, destroy: destroy };
}

/**
 * The page component. The SDK exposes no React hooks and the runtime loader maps only
 * `react/jsx-runtime`, so this is a pure-jsx shell whose ref callback mounts the vanilla
 * designer. `mount` is created once (stable identity), so React attaches it on mount and calls
 * it with null on unmount instead of remounting the canvas on every host re-render.
 */
function createWorkflowsPage(call) {
  let mounted = null;

  function mount(node) {
    if (!node) {
      // ref(null): React has detached the page, so the observer and drag listeners must go
      // too. Without this, fit() kept running against a canvas nobody could see.
      if (mounted && mounted.__vwDesigner) mounted.__vwDesigner.destroy();
      mounted = null;
      return;
    }
    if (node.__vwDesigner) { mounted = node; return; }
    node.__vwDesigner = createDesigner(node, call);
    mounted = node;
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
