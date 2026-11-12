/**
 * Replays Stage 7's delivery, one screwdriving operation at a time, as if the robot
 * cell were running now.
 *
 *   aursad/raw     a block of rows of the current operation (z-scored, as the agent sees them)
 *   aursad/op      start / end of an operation; `reset` on a restart
 *   aursad/status  transport, operation, channels and z-score stats (retained)
 *   aursad/labels  the held-back labels, once revealed (retained)
 *   aursad/control the page's clicks: play, pause, restart, reveal, pace, select (a session)
 *
 * - IN RECORDING ORDER, at a chosen pace: 1 = real time (100 rows/s, an operation in
 *   10.24 s), 4 (default) or 16.
 * - PACED BY THE AGENT: after an operation's last row the replayer waits for its
 *   result on `omega/results` before starting the next, and it streams nothing until
 *   the serving bridge says it is running.
 * - LABELS ARE HELD BACK, as in Stage 7: they go out on `aursad/labels` only when the
 *   viewer reveals them, or when the delivery has been played to the end.
 *
 * Env (app-serving/.env): MQTT_PORT, PACE.
 */
import fs from 'node:fs';
import path from 'node:path';
import mqtt from 'mqtt';
import { REPO, loadEnv, readJson } from './common.js';

loadEnv();
const MQTT_PORT = Number(process.env.MQTT_PORT ?? 1893);
const BROKER_URL = process.env.BROKER ?? `mqtt://127.0.0.1:${MQTT_PORT}`;
const BLOCK = 32;
const SAMPLE_HZ = 100;
const PACES = [1, 4, 16];

const manifest = readJson(path.join(REPO, 'data', 'roles', 'manifest.json'));
if (!manifest) {
	console.error('replayer: no data/roles/manifest.json');
	process.exit(1);
}
const labelsFile = readJson(path.join(REPO, 'data', 'roles', 'labels', 'delivery.json'));
const LABELS = Object.fromEntries((labelsFile?.operations ?? []).map((o) => [o.file, o.class]));
/** Every delivery operation, in recording order, with its recording session (timestamps
 *  were offset by 100,000 s per session in Stage 1b). */
const ALL = manifest.files
	.filter((f) => f.role === 'delivery')
	.sort((a, b) => a.start - b.start)
	.map((f) => ({ file: path.basename(f.path), path: path.join(REPO, f.path), session: Math.floor(f.start / 100_000) }));
const SESSIONS = [...new Set(ALL.map((o) => o.session))].map((id) => ({
	id,
	operations: ALL.filter((o) => o.session === id).length
}));
/** The operations being replayed: all of them, or one session's. */
let OPS = ALL;
let session = null;
const settings = readJson(path.join(REPO, 'eval_out', 'settings.json'));

function readOperation(file) {
	const lines = fs.readFileSync(file, 'utf8').trim().split('\n');
	const header = lines[0].split(',');
	const cols = manifest.channels.map((c) => header.indexOf(c));
	return lines.slice(1).map((l) => {
		const v = l.split(',');
		return cols.map((i) => Number(v[i]));
	});
}

const st = {
	playing: false,
	ended: false,
	pace: PACES.includes(Number(process.env.PACE)) ? Number(process.env.PACE) : 4,
	op: 0,
	rowsSent: 0,
	revealed: false,
	waiting: false
};
let agentRunning = false;
let generation = 0;
/** @type {((op: number) => void) | null} */
let onResult = null;

function status() {
	client.publish(
		'aursad/status',
		JSON.stringify({
			...st,
			opCount: OPS.length,
			session,
			sessions: SESSIONS,
			totalOperations: ALL.length,
			file: OPS[st.op]?.file ?? null,
			rowsPerOp: 1024,
			sampleHz: SAMPLE_HZ,
			window: settings?.window ?? null,
			channels: manifest.channels,
			detectorChannels: settings?.channels ?? null,
			zscore: manifest.zscore,
			sourceColumns: manifest.source_columns,
			dataset: manifest.dataset
		}),
		{ retain: true }
	);
}

function publishLabels() {
	const played = st.ended ? OPS.length : st.op;
	const labels = Object.fromEntries(OPS.slice(0, played).map((o) => [o.file, LABELS[o.file] ?? null]));
	client.publish('aursad/labels', JSON.stringify({ revealed: st.revealed || st.ended, labels }), { retain: true });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitUntil(cond, gen) {
	while (!cond()) {
		if (gen !== generation) return false;
		await sleep(100);
	}
	return gen === generation;
}

/** The generation whose loop is alive, so a pause and play never starts a second one. */
let looping = -1;

/** Play from the current operation until restarted or done (a pause waits inside). */
async function loop() {
	const gen = generation;
	if (looping === gen) return;
	looping = gen;
	try {
		await play(gen);
	} finally {
		if (looping === gen) looping = -1;
	}
}

async function play(gen) {
	while (st.op < OPS.length) {
		if (!(await waitUntil(() => st.playing && agentRunning, gen))) return;
		const op = OPS[st.op];
		const rows = readOperation(op.path);
		if (st.rowsSent === 0) client.publish('aursad/op', JSON.stringify({ event: 'start', op: st.op, file: op.file }));
		while (st.rowsSent < rows.length) {
			if (!(await waitUntil(() => st.playing, gen))) return;
			const block = rows.slice(st.rowsSent, st.rowsSent + BLOCK);
			client.publish('aursad/raw', JSON.stringify({ op: st.op, file: op.file, offset: st.rowsSent, rows: block }));
			st.rowsSent += block.length;
			if (st.rowsSent % (BLOCK * 8) === 0) status();
			await sleep((BLOCK / SAMPLE_HZ / st.pace) * 1000);
			if (gen !== generation) return;
		}
		// The whole operation is out: the bridge sends it as one query. Wait for its answer.
		st.waiting = true;
		status();
		const answered = new Promise((resolve) => {
			onResult = (n) => n === st.op && resolve(true);
			setTimeout(() => resolve(false), 120_000);
		});
		client.publish('aursad/op', JSON.stringify({ event: 'end', op: st.op, file: op.file, rows: rows.length }));
		const ok = await answered;
		onResult = null;
		if (gen !== generation) return;
		if (!ok) console.warn(`replayer: no result for ${op.file} after 120 s; moving on`);
		st.waiting = false;
		st.op++;
		st.rowsSent = 0;
		if (st.revealed) publishLabels();
		status();
		await sleep(400 / st.pace);
	}
	st.ended = true;
	st.playing = false;
	publishLabels();
	status();
	console.log(`replayer: all ${OPS.length} delivery operations played; labels revealed`);
}

function restart() {
	generation++;
	Object.assign(st, { playing: false, ended: false, op: 0, rowsSent: 0, revealed: false, waiting: false });
	client.publish('aursad/op', JSON.stringify({ event: 'reset' }));
	publishLabels();
	status();
}

const client = mqtt.connect(BROKER_URL, { clientId: `aursad-replayer-${Date.now()}` });
client.on('connect', () => {
	client.subscribe(['aursad/control', 'omega/agent', 'omega/results'], { qos: 1 });
	console.log(`replayer: connected to ${BROKER_URL}; ${OPS.length} delivery operations, pace ${st.pace}x`);
	publishLabels();
	status();
});
client.on('message', (topic, payload) => {
	let msg;
	try {
		msg = JSON.parse(payload.toString());
	} catch {
		return;
	}
	if (topic === 'omega/agent') {
		agentRunning = msg.phase === 'running';
		return;
	}
	if (topic === 'omega/results') {
		onResult?.(msg.op);
		return;
	}
	const { action, value } = msg;
	if (action === 'play') {
		if (st.ended) restart();
		const was = st.playing;
		st.playing = true;
		status();
		if (!was) loop();
	} else if (action === 'pause') {
		st.playing = false;
		status();
	} else if (action === 'restart') {
		restart();
	} else if (action === 'reveal') {
		st.revealed = true;
		publishLabels();
		status();
	} else if (action === 'select') {
		session = value === null || value === 'all' ? null : Number(value);
		OPS = session === null ? ALL : ALL.filter((o) => o.session === session);
		restart();
	} else if (action === 'pace' && PACES.includes(Number(value))) {
		st.pace = Number(value);
		status();
	}
});
for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP'])
	process.on(sig, () => {
		client.publish('aursad/status', JSON.stringify({ ...st, playing: false, stopped: true }), { retain: true }, () =>
			client.end(false, {}, () => process.exit(0))
		);
	});
