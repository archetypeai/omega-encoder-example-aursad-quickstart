/**
 * The agent's local end: a bridge between the local broker and a serving session of
 * the Omega Encoder agent on the Archetype AI platform.
 *
 *   aursad/raw ──► bridge: the operation's 1,024 rows ──POST /query──► serving session
 *   aursad/op  ──► (end of operation: send it)                          (window = frozen)
 *                     ▲                                                    │
 *                     └── kNN detector (frozen, local) ◄── 4 × 12 × 768 ───┘
 *                                    │
 *                                    └──► omega/results: window scores, score, alarm, view points
 *
 * - THE BROWSER NEVER HOLDS THE API KEY. The bridge reads it from the repo's .env and
 *   is the only thing that talks to the platform.
 * - THE SAME LIFECYCLE AS STAGE 8 (serve/serve.py): the shipped copy's package
 *   (`omega-aursad`, window 1,024) as a serving deployment, and one serving session
 *   whose `values` set window_size and step_size to the window Stage 5 froze.
 * - THE DETECTOR RUNS HERE. The agent returns embeddings only; scripts/detector.js is
 *   detect.py's frozen kNN, loaded from out/app/ (scripts/export_detector.py). Each
 *   score is checked against Stage 7's batch score for the same operation, when there
 *   is one, and the difference is logged and published.
 * - A QUERY IS ONE OPERATION. A served session keeps nothing between queries, so the
 *   bridge buffers the operation's rows and sends all 1,024 when the replayer says it
 *   has ended: a whole number of windows, never fewer rows than one window.
 * - ONE SERVING WORKER, HELD WHILE THIS RUNS. On exit the session and the deployment
 *   are ended; their ids sit in out/app_serving_state.json until then, and the next
 *   start ends whatever an earlier bridge left. A session closed after 30 idle minutes
 *   (or a deployment stopped after 20, on dev) is replaced on the next operation.
 * - THE PAGE SEES THE AGENT'S PHASE on `omega/agent` (retained): starting, waiting,
 *   running, replacing, stopped. An MQTT will clears a stale "running" if this process
 *   dies without saying so.
 *
 * Env (repo .env): ATAI_API_ENDPOINT, ATAI_API_KEY. Env (app-serving/.env): MQTT_PORT.
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import mqtt from 'mqtt';
import { REPO, loadEnv, readJson } from './common.js';
import { loadDetector } from './detector.js';

loadEnv();

const ROOT = (process.env.ATAI_API_ENDPOINT ?? '')
	.replace(/\/+$/, '')
	.replace(/\/api$/, '')
	.replace(/\/v\d+(\.\d+)*$/, '');
const API = ROOT ? `${ROOT}/api` : '';
const KEY = process.env.ATAI_API_KEY;
const die = (msg) => {
	console.error(`bridge: ${msg}`);
	process.exit(1);
};
if (!API || !KEY) die('set ATAI_API_ENDPOINT and ATAI_API_KEY in the repo .env');
const MQTT_PORT = Number(process.env.MQTT_PORT ?? 1893);
const BROKER_URL = process.env.BROKER ?? `mqtt://127.0.0.1:${MQTT_PORT}`;
const STATE = path.join(REPO, 'out', 'app_serving_state.json');

// The embed stage's ids, for this key and endpoint (the same fingerprint as embed.py).
const embedState = readJson(path.join(REPO, 'out', 'embed', 'state.json'));
const identity = crypto.createHash('sha256').update(`${API}|${KEY}`).digest('hex').slice(0, 12);
if (!embedState) die('no out/embed/state.json: run Stages 4-5 first (README)');
if (embedState.identity !== identity)
	die('out/embed/state.json was written with another API key or endpoint: run Stages 4-5 with this one');
const PACKAGE = embedState.windows?.['1024']?.package;
if (!PACKAGE) die('no package of omega-aursad (window 1,024) in out/embed/state.json: run Stage 4');
const detector = loadDetector();
if (!detector) die('no out/app/detector.json: run python app-serving/scripts/export_detector.py');
const settings = readJson(path.join(REPO, 'eval_out', 'settings.json'));
if (settings && settings.window !== detector.meta.window)
	die(`out/app/ is for window ${detector.meta.window}, eval_out/settings.json says ${settings.window}: export again`);
const WINDOW = detector.meta.window;
const EXPECTED = detector.meta.expected_delivery_scores ?? {};

async function api(method, p, body) {
	const r = await fetch(`${API}/agents${p}`, {
		method,
		headers: { Authorization: `Bearer ${KEY}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
		body: body ? JSON.stringify(body) : undefined,
		signal: AbortSignal.timeout(120_000)
	});
	const text = await r.text();
	if (!r.ok) {
		const e = new Error(`${method} ${p} → ${r.status}: ${text.slice(0, 300)}`);
		e.status = r.status;
		throw e;
	}
	return text ? JSON.parse(text) : {};
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const live = { deployment: null, session: null, running: false, phase: 'starting' };
const latencies = [];
const save = () =>
	fs.writeFileSync(STATE, JSON.stringify({ endpoint: API, deployment: live.deployment, session: live.session }, null, 1));

/** What the page shows about the agent (retained, so a reload sees it at once). */
function announce(phase, detail = '') {
	live.phase = phase;
	const ms = [...latencies].sort((a, b) => a - b);
	client.publish(
		'omega/agent',
		JSON.stringify({
			phase,
			detail,
			running: live.running,
			deployment: live.deployment,
			session: live.session,
			package: PACKAGE,
			window: WINDOW,
			detector: {
				group: detector.meta.group,
				channels: detector.meta.channels,
				pca: detector.meta.pca,
				k: detector.meta.k,
				match: detector.meta.match,
				threshold: detector.meta.threshold,
				validationAuroc: detector.meta.validation_auroc,
				windowsPerOperation: detector.meta.windows_per_operation
			},
			queued: queue.length,
			medianLatencyMs: ms[Math.floor(ms.length / 2)] ?? null
		}),
		{ retain: true }
	);
}

async function waitFor(kind, id, want, timeoutMs = 600_000) {
	const t0 = Date.now();
	for (;;) {
		const s = (await api('GET', `/${kind}/${id}`)).status;
		if (s === want) return;
		if (['failed', 'stopped', 'completed', 'cancelled'].includes(s) || Date.now() - t0 > timeoutMs)
			throw new Error(`${kind.slice(0, -1)} ${id} is ${s}`);
		await sleep(2000);
	}
}

/** End a session or deployment, as atai_api.end_session / end_deployment do; true once gone. */
async function end(kind, id) {
	if (!id) return true;
	try {
		const s = (await api('GET', `/${kind}/${id}`)).status;
		const done = kind === 'sessions' ? ['completed', 'failed', 'cancelled'] : ['stopped', 'failed'];
		if (!done.includes(s)) await api('POST', `/${kind}/${id}/${kind === 'sessions' ? 'cancel' : 'stop'}`, {});
		await api('DELETE', `/${kind}/${id}`);
		return true;
	} catch (e) {
		if (e.status === 404) return true;
		console.error(`bridge: ${e.message}`);
		return false;
	}
}

async function start() {
	live.running = false;
	announce('starting', 'creating a serving deployment');
	live.deployment = (
		await api('POST', '/deployments', { package_id: PACKAGE, kind: 'serving', sessions: { max: 2 } })
	).id;
	save();
	await waitFor('deployments', live.deployment, 'ready');
	announce('starting', `opening a session at window ${WINDOW}`);
	live.session = (
		await api('POST', '/sessions', {
			deployment_id: live.deployment,
			values: { window_size: WINDOW, step_size: WINDOW }
		})
	).id;
	save();
	await waitFor('sessions', live.session, 'running');
	live.running = true;
	announce('running');
	console.log(
		`bridge: serving deployment ${live.deployment} (package ${PACKAGE}), session ${live.session} at window ${WINDOW}: running`
	);
}

/** Start, retrying while no serving worker is free. */
async function startWithRetry() {
	for (let wait = 15_000; !stopping; wait = Math.min(wait * 2, 120_000)) {
		try {
			await start();
			drain();
			return;
		} catch (e) {
			console.error(`bridge: could not start serving (${e.message}); retrying in ${wait / 1000} s`);
			announce('waiting', `retrying in ${wait / 1000} s`);
			await end('sessions', live.session);
			await end('deployments', live.deployment);
			live.session = live.deployment = null;
			await sleep(wait);
		}
	}
}

async function replace(why) {
	console.warn(`bridge: ${why}; replacing the session and deployment`);
	announce('replacing', why);
	live.running = false;
	await end('sessions', live.session);
	await end('deployments', live.deployment);
	live.session = live.deployment = null;
	await startWithRetry();
}

let stopping = false;
async function shutdown(sig) {
	if (stopping) return;
	stopping = true;
	console.log(`bridge: ${sig}, ending the serving session and deployment`);
	live.running = false;
	const sessionEnded = await end("sessions", live.session);
	const ok = (await end("deployments", live.deployment)) && sessionEnded;
	if (ok) {
		fs.rmSync(STATE, { force: true });
		console.log(`bridge: ended session ${live.session ?? '(none)'} and deployment ${live.deployment ?? '(none)'}`);
	} else {
		console.error(`bridge: not everything was ended; ids in ${path.relative(REPO, STATE)} (the next start ends them)`);
	}
	announce('stopped');
	await new Promise((r) => client.end(false, {}, r));
	process.exit(ok ? 0 : 1);
}
for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(sig, () => shutdown(sig));
process.on('uncaughtException', (e) => {
	console.error('bridge:', e);
	shutdown('error');
});
process.on('unhandledRejection', (e) => {
	console.error('bridge:', e);
	shutdown('error');
});

/** Rows of the operation being replayed, by operation index. */
const buffers = new Map();
const queue = [];
let busy = false;

function onRaw(msg) {
	const rows = buffers.get(msg.op) ?? [];
	rows.push(...msg.rows);
	buffers.set(msg.op, rows);
}

function onOp(msg) {
	if (msg.event === 'reset') {
		buffers.clear();
		queue.length = 0;
		history = [];
		client.publish('omega/history', '[]', { retain: true });
		return;
	}
	if (msg.event !== 'end') return;
	const rows = buffers.get(msg.op) ?? [];
	buffers.delete(msg.op);
	queue.push({ op: msg.op, file: msg.file, rows });
	drain();
}

async function drain() {
	if (busy || !live.running) return;
	busy = true;
	try {
		while (queue.length && live.running && !stopping) {
			const job = queue.shift();
			if (job.rows.length % WINDOW || !job.rows.length) {
				publish({ op: job.op, file: job.file, error: `${job.rows.length} rows: not whole windows of ${WINDOW}` });
				continue;
			}
			const n = job.rows[0].length;
			const body = {
				query: '',
				events: [
					{
						type: 'data.numeric_array',
						event_data: { contents: Array.from({ length: n }, (_, c) => job.rows.map((r) => r[c])) }
					}
				]
			};
			const t = Date.now();
			let answer;
			try {
				answer = await api('POST', `/sessions/${live.session}/query`, body);
			} catch (e) {
				if ([404, 409, 410].includes(e.status)) {
					queue.unshift(job);
					await replace(`session ${live.session} is gone (${e.status})`);
					continue;
				}
				console.error(`bridge: query failed: ${e.message}`);
				publish({ op: job.op, file: job.file, error: `query failed (${e.status ?? 'network'})` });
				continue;
			}
			const latencyMs = Date.now() - t;
			latencies.push(latencyMs);
			if (latencies.length > 200) latencies.shift();
			const records = [...((answer.response ?? answer).data ?? [])].sort(
				(a, b) => (a.start_timestamp ?? 0) - (b.start_timestamp ?? 0)
			);
			let r;
			try {
				r = detector.scoreOperation(records);
			} catch (e) {
				console.error(`bridge: ${job.file}: ${e.message}`);
				publish({ op: job.op, file: job.file, error: e.message });
				continue;
			}
			const batch = EXPECTED[job.file];
			const check = batch === undefined ? null : Math.abs(r.score - batch) / Math.abs(batch);
			console.log(
				`bridge: ${job.file}  score ${r.score.toFixed(4)}${r.alarm ? '  ALARM' : ''}` +
					(batch === undefined ? '' : `  (Stage 7 batch ${batch.toFixed(4)}, rel. diff ${check.toExponential(1)})`) +
					`  ${latencyMs} ms`
			);
			publish({ op: job.op, file: job.file, ...r, threshold: detector.meta.threshold, latencyMs, batchScore: batch ?? null });
			if (latencies.length % 10 === 0) announce('running');
		}
	} finally {
		busy = false;
	}
}

const client = mqtt.connect(BROKER_URL, {
	clientId: `aursad-serving-bridge-${Date.now()}`,
	will: { topic: 'omega/agent', payload: JSON.stringify({ phase: 'stopped', running: false }), retain: true, qos: 1 }
});
/** Every result since the last reset, retained on omega/history so a page opened
 *  mid-replay (or reloaded) sees the whole delivery so far. */
let history = [];
const publish = (msg) => {
	client.publish('omega/results', JSON.stringify(msg));
	history = [...history.filter((r) => r.op !== msg.op), msg];
	client.publish('omega/history', JSON.stringify(history), { retain: true });
};

let started = false;
client.on('connect', async () => {
	client.subscribe(['aursad/raw', 'aursad/op'], { qos: 1 });
	console.log(`bridge: connected to ${BROKER_URL}; ${API}`);
	if (started) return;
	started = true;
	const left = readJson(STATE);
	if (left) {
		console.log(`bridge: ending what an earlier bridge left (session ${left.session}, deployment ${left.deployment})`);
		await end('sessions', left.session);
		await end('deployments', left.deployment);
		fs.rmSync(STATE, { force: true });
	}
	await startWithRetry();
});
client.on('message', (topic, payload) => {
	let msg;
	try {
		msg = JSON.parse(payload.toString());
	} catch {
		return;
	}
	if (topic === 'aursad/raw') onRaw(msg);
	else if (topic === 'aursad/op') onOp(msg);
});
