/**
 * The kNN detector detect/detect.py froze, in JavaScript, for the serving bridge.
 *
 * The Omega Encoder agent answers with embeddings only: one record per window,
 * `channel_<i>` → 768 numbers, i in the file's column order. Scoring is ours, the
 * same arithmetic as detect.py's Detector:
 *
 *   window joint state = the detector's channels, each L2-normalised, concatenated
 *   minus the library mean, times the PCA projection when the settings use one
 *   window score     = mean distance to its k nearest library windows (any window,
 *                      or only those at the same position in their operation)
 *   operation score  = its worst window
 *
 * Loaded from out/app/detector.{json,bin}, written by scripts/export_detector.py.
 */
import fs from 'node:fs';
import path from 'node:path';
import { REPO } from './common.js';

const DIR = path.join(REPO, 'out', 'app');

export function loadDetector() {
	const metaFile = path.join(DIR, 'detector.json');
	if (!fs.existsSync(metaFile)) return null;
	const meta = JSON.parse(fs.readFileSync(metaFile, 'utf8'));
	const buf = fs.readFileSync(path.join(DIR, 'detector.bin'));
	const take = (name) => {
		const l = meta.layout[name];
		if (!l) return null;
		const n = l.shape.reduce((a, b) => a * b, 1);
		return new Float32Array(buf.buffer, buf.byteOffset + l.offset, n);
	};
	const mean = take('mean');
	const proj = take('proj');
	const library = take('library');
	const viewMean = take('view_mean');
	const viewAxes = take('view_axes');
	const { dim: d, projected_dim: p, windows_per_operation: w, library_operations: n, k, match } = meta;

	/** One window's record → its point in the detector's space (Float64Array of p). */
	function point(rec) {
		const x = new Float64Array(d);
		let o = 0;
		for (const ci of meta.channel_index) {
			const e = rec[`channel_${ci}`];
			if (!Array.isArray(e) || e.length !== meta.embedding_dim)
				throw new Error(`window has no 768-d channel_${ci}`);
			let norm = 0;
			for (const v of e) norm += v * v;
			norm = Math.max(Math.sqrt(norm), 1e-8);
			for (let i = 0; i < e.length; i++, o++) x[o] = e[i] / norm - mean[o];
		}
		if (!proj) return x;
		const y = new Float64Array(p);
		for (let i = 0; i < d; i++) {
			const xi = x[i];
			if (xi === 0) continue;
			const row = i * p;
			for (let j = 0; j < p; j++) y[j] += xi * proj[row + j];
		}
		return y;
	}

	/** Mean distance from `x` to its k nearest library windows (all, or position `pos`). */
	function knn(x, pos) {
		const dists = [];
		for (let op = 0; op < n; op++) {
			for (let j = 0; j < w; j++) {
				if (match === 'position' && j !== pos) continue;
				const base = (op * w + j) * p;
				let s = 0;
				for (let i = 0; i < p; i++) {
					const dv = x[i] - library[base + i];
					s += dv * dv;
				}
				dists.push(Math.sqrt(s));
			}
		}
		dists.sort((a, b) => a - b);
		let s = 0;
		for (let i = 0; i < k; i++) s += dists[i];
		return s / k;
	}

	/** PCA 1-2 of the library, for the page's embedding view. */
	function view(x) {
		let a = 0;
		let b = 0;
		for (let i = 0; i < p; i++) {
			const v = x[i] - viewMean[i];
			a += v * viewAxes[i];
			b += v * viewAxes[p + i];
		}
		return [a, b];
	}

	/** One operation's answer (its records, in window order) → scores and view points. */
	function scoreOperation(records) {
		if (records.length !== w) throw new Error(`${records.length} windows, expected ${w}`);
		const points = records.map(point);
		const windowScores = points.map((x, j) => knn(x, j));
		const score = Math.max(...windowScores);
		return {
			windowScores,
			score,
			worst: windowScores.indexOf(score),
			alarm: score > meta.threshold,
			coords: points.map(view)
		};
	}

	return { meta, scoreOperation };
}
