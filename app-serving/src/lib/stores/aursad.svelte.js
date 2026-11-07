/**
 * The single MQTT-backed store the page reads from. The browser talks to mosquitto
 * directly over WebSockets; there is no backend, and the API key stays with the bridge.
 *
 *   aursad/status  replayer -> transport, operation, channels, z-score stats (retained)
 *   aursad/raw     replayer -> a block of the current operation's rows (z-scored)
 *   aursad/op      replayer -> an operation starts / ends; reset
 *   aursad/labels  replayer -> the held-back labels, once revealed (retained)
 *   omega/results  bridge   -> one scored operation: window scores, score, alarm, view points
 *   omega/history  bridge   -> every result since the last reset (retained)
 *   omega/agent    bridge   -> the serving session's phase (retained)
 *
 * What the detector says comes from `omega/results` only. Labels arrive on their own
 * topic, are withheld until revealed, and never colour a score: a false alarm has to
 * be able to look like one.
 */
import mqtt from 'mqtt';
import { env } from '$env/dynamic/public';

const WS_PORT = env.PUBLIC_MQTT_WS_PORT || '9011';
const TCP_PORT = env.PUBLIC_MQTT_TCP_PORT || '1893';
export const TOPICS = ['aursad/status', 'aursad/raw', 'aursad/op', 'aursad/labels', 'aursad/control', 'omega/results', 'omega/history', 'omega/agent'];
/** Window the per-topic rates are averaged over: a result arrives every few seconds. */
const RATE_WINDOW_MS = 5000;

/** The 12 channels by what they measure, as the README groups them. */
export const GROUPS = [
	{ key: 'screwdriver', label: 'Screwdriver', channels: ['torque_current', 'torque_achieved'] },
	{ key: 'tool', label: 'Tool', channels: ['tcp_force_z', 'tool_acc_x', 'tool_acc_y', 'tool_acc_z'] },
	{
		key: 'arm',
		label: 'Arm',
		channels: ['joint_current_0', 'joint_current_1', 'joint_current_2', 'joint_current_3', 'joint_current_4', 'joint_current_5']
	}
];

/** @type {Record<string, [label: string, unit: string]>} */
export const CHANNEL_META = {
	torque_current: ['Torque, current', ''],
	torque_achieved: ['Torque, achieved', ''],
	tcp_force_z: ['Tool force Z', 'N'],
	tool_acc_x: ['Tool accel. X', 'm/s²'],
	tool_acc_y: ['Tool accel. Y', 'm/s²'],
	tool_acc_z: ['Tool accel. Z', 'm/s²'],
	joint_current_0: ['Joint 0 current', 'A'],
	joint_current_1: ['Joint 1 current', 'A'],
	joint_current_2: ['Joint 2 current', 'A'],
	joint_current_3: ['Joint 3 current', 'A'],
	joint_current_4: ['Joint 4 current', 'A'],
	joint_current_5: ['Joint 5 current', 'A']
};

/** @type {Record<string, string>} */
export const CLASS_LABEL = {
	normal: 'normal',
	damaged_screw: 'damaged screw',
	extra_component: 'extra component',
	missing_screw: 'missing screw'
};

export function brokerLabel() {
	return `MQTT (mosquitto) · tcp :${TCP_PORT} · ws :${WS_PORT}`;
}

function emptyState() {
	return {
		connected: false,
		/** @type {any} */ status: null,
		/** @type {any} */ agent: null,
		/** @type {{revealed: boolean, labels: Record<string, string|null>}} */
		labels: { revealed: false, labels: {} },
		/** The operation being replayed: its rows so far, per channel, in library sigmas
		 *  (z-scored with the library's mean and std, as the agent receives them). */
		current: { op: -1, file: '', rows: 0, /** @type {Record<string, number[]>} */ series: {} },
		/** @type {{op:number, file:string, score?:number, windowScores?:number[], worst?:number,
		 *          alarm?:boolean, latencyMs?:number, batchScore?:number|null,
		 *          coords?:number[][], threshold?:number, error?:string}[]} */
		results: [],
		/** Messages per second on each topic, as this tab observes them, for the data-flow view. */
		flows: /** @type {Record<string, number>} */ (Object.fromEntries(TOPICS.map((t) => [t, 0])))
	};
}

class AursadStore {
	state = $state(emptyState());
	/** @type {{points: number[][], explained: number[], window: number, windows_per_operation: number} | null} */
	view = $state.raw(null);
	/** @type {import('mqtt').MqttClient | null} */
	#client = null;
	/** @type {Record<string, number[]>} */
	#arrivals = Object.fromEntries(TOPICS.map((t) => [t, []]));
	/** @type {ReturnType<typeof setInterval> | null} */
	#timer = null;

	connect() {
		if (this.#client) return;
		const url = typeof location === 'undefined' ? `ws://127.0.0.1:${WS_PORT}` : `ws://${location.hostname}:${WS_PORT}`;
		this.#client = mqtt.connect(url, { clientId: `aursad-app-${Math.random().toString(16).slice(2)}` });
		this.#client.on('connect', () => {
			this.state.connected = true;
			this.#client?.subscribe(TOPICS, { qos: 0 });
			this.#loadView();
		});
		this.#client.on('close', () => (this.state.connected = false));
		this.#client.on('error', () => (this.state.connected = false));
		this.#client.on('message', (topic, payload) => this.#onMessage(topic, payload));
		this.#timer = setInterval(() => {
			const now = Date.now();
			/** @type {Record<string, number>} */
			const flows = {};
			for (const t of TOPICS) {
				this.#arrivals[t] = this.#arrivals[t].filter((x) => now - x < RATE_WINDOW_MS);
				flows[t] = this.#arrivals[t].length / (RATE_WINDOW_MS / 1000);
			}
			this.state.flows = flows;
		}, 1000);
	}

	disconnect() {
		if (this.#timer) clearInterval(this.#timer);
		this.#client?.end(true);
		this.#client = null;
		this.state = emptyState();
	}

	async #loadView() {
		if (this.view) return;
		try {
			this.view = await fetch('/library-view.json').then((r) => r.json());
		} catch {
			this.view = null;
		}
	}

	/** @param {string} topic @param {Uint8Array} payload */
	#onMessage(topic, payload) {
		this.#arrivals[topic]?.push(Date.now());
		if (topic === 'aursad/control') return;
		let msg;
		try {
			msg = JSON.parse(payload.toString());
		} catch {
			return;
		}
		const s = this.state;
		if (topic === 'aursad/status') s.status = msg;
		else if (topic === 'omega/agent') s.agent = msg;
		else if (topic === 'aursad/labels') s.labels = msg;
		else if (topic === 'aursad/op') {
			if (msg.event === 'reset') {
				s.results = [];
				s.current = { op: -1, file: '', rows: 0, series: {} };
			} else if (msg.event === 'start') {
				s.current = { op: msg.op, file: msg.file, rows: 0, series: {} };
			}
		} else if (topic === 'aursad/raw') this.#onRaw(msg);
		else if (topic === 'omega/history') {
			if (Array.isArray(msg)) s.results = msg.sort((/** @type {any} */ a, /** @type {any} */ b) => a.op - b.op);
		} else if (topic === 'omega/results') {
			s.results = [...s.results.filter((r) => r.op !== msg.op), msg].sort((a, b) => a.op - b.op);
		}
	}

	/** @param {{op:number, file:string, offset:number, rows:number[][]}} msg */
	#onRaw(msg) {
		const s = this.state;
		const channels = s.status?.channels;
		if (!channels) return;
		if (msg.op !== s.current.op) s.current = { op: msg.op, file: msg.file, rows: 0, series: {} };
		/** @type {Record<string, number[]>} */
		const series = s.current.series;
		channels.forEach((/** @type {string} */ c, /** @type {number} */ i) => {
			const arr = (series[c] ??= []);
			for (const row of msg.rows) arr.push(row[i]);
		});
		s.current.rows = msg.offset + msg.rows.length;
	}

	/** A z-scored value back in the channel's engineering units. @param {string} c @param {number} v */
	units(c, v) {
		const z = this.state.status?.zscore;
		return z ? v * z.std[c] + z.mean[c] : v;
	}

	/** The result for an operation, if it has been scored. @param {number} op */
	result(op) {
		return this.state.results.find((r) => r.op === op) ?? null;
	}

	/** Totals over the scored operations; against the labels once they are revealed. */
	get totals() {
		const s = this.state;
		const scored = s.results.filter((r) => r.score !== undefined);
		const lat = scored.map((r) => r.latencyMs ?? 0).sort((a, b) => a - b);
		const out = {
			scored: scored.length,
			alarms: scored.filter((r) => r.alarm).length,
			medianLatencyMs: lat.length ? lat[Math.floor(lat.length / 2)] : null,
			/** @type {null | {caught:number, anomalies:number, falseAlarms:number, normals:number,
			 *                 byClass: Record<string, {caught:number, total:number}>}} */
			truth: null
		};
		if (s.labels.revealed) {
			/** @type {{caught:number, anomalies:number, falseAlarms:number, normals:number, byClass: Record<string, {caught:number, total:number}>}} */
			const t = { caught: 0, anomalies: 0, falseAlarms: 0, normals: 0, byClass: {} };
			for (const r of scored) {
				const c = s.labels.labels[r.file];
				if (!c) continue;
				if (c === 'normal') {
					t.normals++;
					if (r.alarm) t.falseAlarms++;
				} else {
					t.anomalies++;
					if (r.alarm) t.caught++;
					const b = (t.byClass[c] ??= { caught: 0, total: 0 });
					b.total++;
					if (r.alarm) b.caught++;
				}
			}
			out.truth = t;
		}
		return out;
	}

	/** @param {string} action @param {unknown} [value] */
	#publish(action, value) {
		this.#client?.publish('aursad/control', JSON.stringify({ action, value }));
	}
	play() {
		this.#publish('play');
	}
	pause() {
		this.#publish('pause');
	}
	restart() {
		this.#publish('restart');
	}
	reveal() {
		this.#publish('reveal');
	}
	/** @param {number | 'all'} session a recording session, or all of them */
	select(session) {
		this.#publish('select', session);
	}
	/** @param {number} pace */
	setPace(pace) {
		this.#publish('pace', pace);
	}
}

export const aursad = new AursadStore();
