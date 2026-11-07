<script>
	/**
	 * The robot cell, as a draughtsman's plate in the sibling monitors' style (the pump,
	 * the washing machine, the TEP flowsheet): a UR3e arm with an OnRobot screwdriver over
	 * the aluminium plate it drives screws into, with numbered callouts and a key of the
	 * live readings under it.
	 *
	 * Ink only, except the two things that carry state:
	 * - the screwdriver's bit and the screw: rotation marks while the torque is on (the
	 *   tightening in progress), and the last scored tightening's verdict colour once it
	 *   has an answer;
	 * - callout 4, the arm's joints, drawn muted: the agent embeds their currents, but the
	 *   frozen detector does not compare them.
	 *
	 * The verdict is the detector's alone: the label, if revealed, is never drawn here.
	 */
	import { scoreTone } from '$lib/scores.js';
	import { cn } from '$lib/utils';

	/** @type {{aursad: any, class?: string}} */
	let { aursad, class: className = '' } = $props();
	const s = $derived(aursad.state);
	const INK = 'var(--plate-ink)';
	const SOFT = 'var(--plate-detail)';
	const last = $derived([...s.results].reverse().find((/** @type {any} */ r) => r.score !== undefined));
	const scoredNow = $derived(last && last.op === s.current.op);
	const tone = $derived(last ? scoreTone(last.score, last.threshold) : null);
	const series = $derived(s.current.series);
	const latest = (/** @type {string} */ c) => {
		const v = series[c]?.at(-1);
		return v === undefined ? null : aursad.units(c, v);
	};
	const torque = $derived(latest('torque_current'));
	const driving = $derived(torque !== null && torque > 0.05 && !scoredNow);
	const used = $derived(new Set(s.status?.detectorChannels ?? s.agent?.detector?.channels ?? []));
	const armUsed = $derived(used.size === 0 || used.has('joint_current_0'));
	const fmt = (/** @type {number | null} */ v, /** @type {number} */ d = 2) => (v === null ? '—' : v.toFixed(d));
	const accel = $derived.by(() => {
		const [x, y, z] = ['tool_acc_x', 'tool_acc_y', 'tool_acc_z'].map(latest);
		return x === null || y === null || z === null ? null : Math.sqrt(x * x + y * y + z * z);
	});
	const BIT = $derived(scoredNow && tone ? tone.color : driving ? INK : SOFT);

	/** @param {number} x0 @param {number} y @param {number} w @param {number} step */
	const hatch = (x0, y, w, step) =>
		Array.from({ length: Math.floor(w / step) }, (_, i) => `M${x0 + i * step},${y + 5} L${x0 + i * step + 4},${y}`);

	const key = $derived([
		{ n: 1, label: 'Screwdriver torque', value: fmt(torque, 3), muted: false },
		{ n: 2, label: 'Tool force Z', value: `${fmt(latest('tcp_force_z'), 1)} N`, muted: false },
		{ n: 3, label: 'Tool accel. |a|', value: `${fmt(accel, 1)} m/s²`, muted: false },
		{ n: 4, label: 'Joint currents', value: armUsed ? `${fmt(latest('joint_current_1'), 2)} A` : 'not compared', muted: !armUsed }
	]);
	const caption = $derived(
		!last
			? 'No call yet'
			: `#${last.op + 1} · ${last.alarm ? 'alarm' : 'normal'} · score ${last.score.toFixed(2)} (threshold ${last.threshold.toFixed(2)})`
	);
</script>

<div class={cn('flex min-h-0 flex-1 flex-col items-center', className)}>
	<div class="flex min-h-0 w-full flex-1 items-center justify-center">
		<svg viewBox="0 0 170 112" class="h-full max-h-[420px] w-full" preserveAspectRatio="xMidYMid meet" font-family="var(--font-mono, ui-monospace, monospace)" role="img" aria-label="Elevation of the robot cell: arm, screwdriver and workpiece plate">
			<!-- ground -->
			<line x1="6" y1="104" x2="164" y2="104" stroke={SOFT} stroke-width="0.6" />
			{#each hatch(6, 104, 158, 5) as d, i (i)}
				<path {d} stroke={SOFT} stroke-width="0.3" opacity="0.55" fill="none" />
			{/each}

			<!-- table and the aluminium workpiece plate with its screw holes -->
			<rect x="78" y="86" width="80" height="4" fill="none" stroke={SOFT} stroke-width="0.6" />
			<path d="M84,90 L84,104 M152,90 L152,104" stroke={SOFT} stroke-width="0.6" />
			<rect x="90" y="82" width="62" height="4" fill="none" stroke={INK} stroke-width="0.7" />
			{#each [96, 106, 116, 126, 136, 146] as x (x)}
				<line x1={x} y1="82" x2={x} y2="86" stroke={SOFT} stroke-width="0.5" stroke-dasharray="0.8 0.8" />
			{/each}

			<!-- the arm: base, shoulder, upper arm, elbow, forearm, wrist -->
			<g stroke={armUsed ? INK : SOFT} fill="none">
				<rect x="20" y="92" width="22" height="12" stroke-width="0.7" />
				<rect x="24" y="80" width="14" height="12" stroke-width="0.7" />
				<circle cx="31" cy="76" r="6" stroke-width="0.8" />
				<path d="M34,71 L66,33 M28,71 L60,29" stroke-width="0.8" />
				<circle cx="63" cy="31" r="4.5" stroke-width="0.8" />
				<path d="M66,28 L106,36 M64,35 L104,42" stroke-width="0.8" />
				<circle cx="108" cy="40" r="3.6" stroke-width="0.8" />
			</g>

			<!-- wrist and tool flange (force/torque and accelerometer live here) -->
			<rect x="104" y="44" width="10" height="5" fill="none" stroke={INK} stroke-width="0.8" />
			<!-- the screwdriver -->
			<rect x="103" y="49" width="12" height="18" fill="none" stroke={INK} stroke-width="0.8" />
			<path d="M106,53 L112,53 M106,56 L112,56 M106,59 L112,59" stroke={SOFT} stroke-width="0.4" />
			<path d="M107,67 L111,67 L110,72 L108,72 Z" fill="none" stroke={INK} stroke-width="0.7" />
			<!-- bit and screw: the only parts that carry state -->
			<line x1="109" y1="72" x2="109" y2="80" stroke={BIT} stroke-width="1" />
			<path d="M106.5,80 L111.5,80 L110.5,82 L107.5,82 Z" fill={scoredNow && tone ? tone.color : 'none'} stroke={BIT} stroke-width="0.6" />
			<line x1="109" y1="82" x2="109" y2="86" stroke={BIT} stroke-width="0.7" stroke-dasharray="0.6 0.6" />
			{#if driving}
				<g stroke={INK} stroke-width="0.5" fill="none">
					<path d="M104,76 A6,3 0 0,0 114,76" />
					<path d="M112.6,75 L114,76 L112.4,77.2" />
				</g>
			{/if}

			<!-- callouts -->
			{#each [
				{ n: 1, x: 126, y: 58, tx: 115, ty: 58 },
				{ n: 2, x: 126, y: 44, tx: 114, ty: 46.5 },
				{ n: 3, x: 92, y: 52, tx: 103, ty: 47 },
				{ n: 4, x: 48, y: 18, tx: 61, ty: 28 }
			] as c (c.n)}
				{@const muted = c.n === 4 && !armUsed}
				<line x1={c.x} y1={c.y} x2={c.tx} y2={c.ty} stroke={muted ? SOFT : INK} stroke-width="0.4" />
				<circle cx={c.x} cy={c.y} r="3.2" fill="var(--color-background)" stroke={muted ? SOFT : INK} stroke-width="0.5" />
				<text x={c.x} y={c.y + 1.4} text-anchor="middle" font-size="3.8" fill={muted ? SOFT : INK}>{c.n}</text>
			{/each}
		</svg>
	</div>
	<p class="pt-1 text-xs" style={tone && last ? `color: ${tone.color}` : ''} class:text-muted-foreground={!last}>{caption}</p>
	<div class="flex flex-wrap justify-center gap-x-5 gap-y-1 pt-3 text-xs">
		{#each key as k (k.n)}
			<span class={k.muted ? 'text-muted-foreground' : ''}>
				{k.n}. {k.label} <span class="font-mono tabular-nums">{k.value}</span>
			</span>
		{/each}
	</div>
</div>
