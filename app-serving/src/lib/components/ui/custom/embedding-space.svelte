<script>
	/**
	 * The detector's space, in two dimensions: the 600 library windows (150 normal
	 * tightenings × 4) in PCA 1-2 of their joint states, whitened, from
	 * scripts/export_detector.py. Each scored operation adds its windows through the
	 * same projection: the last operation large and numbered by window, the ones
	 * before it as a fading trail.
	 *
	 * Two of 4,608 dimensions (37% of the variance): a window far from the cloud here
	 * is far from it, but one inside the cloud here can still be far in the others.
	 */
	import { scoreTone } from '$lib/scores.js';
	import { cn } from '$lib/utils';

	/** @type {{aursad: any, class?: string}} */
	let { aursad, class: className = '' } = $props();
	const s = $derived(aursad.state);
	const view = $derived(aursad.view);
	const scored = $derived(s.results.filter((/** @type {any} */ r) => r.coords));
	const last = $derived(scored.at(-1));
	const trail = $derived(scored.slice(-13, -1));

	const all = $derived([
		...(view?.points ?? []).map((/** @type {number[]} */ p) => [p[0], p[1]]),
		...scored.flatMap((/** @type {any} */ r) => r.coords)
	]);
	const xs = $derived(all.map((p) => p[0]));
	const ys = $derived(all.map((p) => p[1]));
	const pad = 0.4;
	const x0 = $derived(Math.min(-3, ...xs) - pad);
	const x1 = $derived(Math.max(3, ...xs) + pad);
	const y0 = $derived(Math.min(-3, ...ys) - pad);
	const y1 = $derived(Math.max(3, ...ys) + pad);
	const W = 400;
	const H = 300;
	const sx = (/** @type {number} */ v) => ((v - x0) / (x1 - x0)) * W;
	const sy = (/** @type {number} */ v) => H - ((v - y0) / (y1 - y0)) * H;
</script>

<div class={cn('flex min-h-0 flex-col gap-2', className)}>
	{#if view}
		<svg viewBox="0 0 {W} {H}" class="min-h-0 w-full flex-1" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Embedding space">
			{#each view.points as p, i (i)}
				<circle cx={sx(p[0])} cy={sy(p[1])} r="2" class="fill-muted-foreground" opacity="0.28" />
			{/each}
			{#each trail as r, t (r.op)}
				{#each r.coords as c, j (j)}
					<circle
						cx={sx(c[0])}
						cy={sy(c[1])}
						r="2.6"
						style="fill: {scoreTone(r.windowScores[j], r.threshold).color}"
						opacity={0.15 + (0.45 * (t + 1)) / trail.length}
					/>
				{/each}
			{/each}
			{#if last}
				<polyline
					points={last.coords.map((/** @type {number[]} */ c) => `${sx(c[0])},${sy(c[1])}`).join(' ')}
					fill="none"
					class="stroke-foreground"
					stroke-width="1"
					opacity="0.5"
				/>
				{#each last.coords as c, j (j)}
					<circle
						cx={sx(c[0])}
						cy={sy(c[1])}
						r={j === last.worst ? 7 : 5}
						style="fill: {scoreTone(last.windowScores[j], last.threshold).color}"
						class="stroke-background"
						stroke-width="1.5"
					/>
					<text x={sx(c[0]) + 8} y={sy(c[1]) + 4} class="fill-foreground font-mono text-[10px]">{j + 1}</text>
				{/each}
			{/if}
		</svg>
		<div class="flex justify-between font-mono text-2xs text-muted-foreground">
			<span>grey: {view.points.length} library windows · PCA 1 ({Math.round(view.explained[0] * 100)}%) × PCA 2 ({Math.round(view.explained[1] * 100)}%)</span>
			<span>{last ? `numbered: #${last.op + 1}'s windows 1–${last.coords.length}; largest = the one that set its score` : 'no tightening yet'}</span>
		</div>
	{:else}
		<p class="m-auto max-w-sm text-center text-sm text-muted-foreground">
			No library view: run <code>python app-serving/scripts/export_detector.py</code> from the repo root.
		</p>
	{/if}
</div>
