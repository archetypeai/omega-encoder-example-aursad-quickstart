<script>
	/**
	 * The current operation's 12 channels as it is replayed: 1,024 rows at 100 Hz,
	 * drawn left to right across a fixed axis so every tightening lines up the same
	 * way (each starts 256 rows before the torque rises).
	 *
	 * Traces are in library sigmas, the values the agent receives, on one shared
	 * scale; the figure on the right is the latest value in engineering units.
	 * Dashed ticks mark the agent's windows. Once the operation is scored, its
	 * worst window (the one that set its score) is shaded.
	 *
	 * Channels the frozen detector does not use are drawn, and muted: the agent
	 * embeds all 12, and Stage 5 chose which ones the kNN compares.
	 */
	import { GROUPS, CHANNEL_META } from '$lib/stores/aursad.svelte.js';
	import { scoreTone } from '$lib/scores.js';
	import { cn } from '$lib/utils';

	/** @type {{aursad: any, class?: string}} */
	let { aursad, class: className = '' } = $props();
	const s = $derived(aursad.state);
	const ROWS = 1024;
	const H = 40;
	const window = $derived(s.status?.window ?? s.agent?.window ?? 1024);
	const used = $derived(new Set(s.status?.detectorChannels ?? s.agent?.detector?.channels ?? []));
	const result = $derived(aursad.result(s.current.op));
	const NAMES = ['before', 'driving', 'finishing', 'after'];
	const segments = $derived(
		Array.from({ length: ROWS / window }, (_, i) => `${i + 1}${ROWS / window === 4 ? ` · ${NAMES[i]}` : ''}`)
	);
	const ticks = $derived(Array.from({ length: Math.max(0, ROWS / window - 1) }, (_, i) => (i + 1) * window));

	/** @param {number[] | undefined} v */
	function path(v) {
		if (!v?.length) return '';
		const lo = Math.min(-3, ...v);
		const hi = Math.max(3, ...v);
		const y = (/** @type {number} */ x) => H - 1 - ((x - lo) / (hi - lo)) * (H - 2);
		let d = '';
		const stride = Math.max(1, Math.floor(v.length / 512));
		for (let i = 0; i < v.length; i += stride) d += `${i ? 'L' : 'M'}${i},${y(v[i]).toFixed(2)}`;
		return d;
	}
</script>

<div class={cn('flex min-h-0 flex-col gap-4 overflow-y-auto pr-1', className)}>
	<div class="grid grid-cols-[8.5rem_1fr_5.5rem] items-end gap-3">
		<span class="font-mono text-2xs text-muted-foreground">agent's windows</span>
		<div class="grid font-mono text-2xs text-muted-foreground" style="grid-template-columns: repeat({segments.length}, 1fr)">
			{#each segments as seg, i (i)}
				<span class={cn('border-l border-border pl-1', result?.worst === i && 'text-foreground')}>{seg}</span>
			{/each}
		</div>
		<span></span>
	</div>
	{#each GROUPS as g (g.key)}
		{@const groupUsed = g.channels.some((c) => used.has(c))}
		<div class="flex flex-col gap-1">
			<div class="flex items-baseline justify-between">
				<span class="font-mono text-2xs tracking-wide text-muted-foreground uppercase">{g.label}</span>
				{#if used.size && !groupUsed}
					<span class="text-2xs text-muted-foreground">embedded; not compared by the detector</span>
				{/if}
			</div>
			{#each g.channels as c (c)}
				{@const v = s.current.series[c]}
				{@const last = v?.at(-1)}
				<div class={cn('grid grid-cols-[8.5rem_1fr_5.5rem] items-center gap-3', used.size && !used.has(c) && 'opacity-45')}>
					<span class="truncate text-xs">{CHANNEL_META[c]?.[0] ?? c}</span>
					<svg viewBox="0 0 {ROWS} {H}" preserveAspectRatio="none" class="h-10 w-full" aria-hidden="true">
						{#if result?.worst !== undefined && result.windowScores}
							<rect
								x={result.worst * window}
								y="0"
								width={window}
								height={H}
								style="fill: {scoreTone(result.score, result.threshold).color}"
								opacity="0.14"
							/>
						{/if}
						{#each ticks as t (t)}
							<line x1={t} x2={t} y1="0" y2={H} class="stroke-border" stroke-dasharray="2 2" vector-effect="non-scaling-stroke" />
						{/each}
						<path d={path(v)} fill="none" class="stroke-foreground" stroke-width="1" vector-effect="non-scaling-stroke" />
					</svg>
					<span class="text-right font-mono text-xs text-muted-foreground tabular-nums">
						{last === undefined ? '—' : aursad.units(c, last).toFixed(Math.abs(aursad.units(c, last)) < 10 ? 3 : 1)}
						<span class="text-2xs">{CHANNEL_META[c]?.[1] ?? ''}</span>
					</span>
				</div>
			{/each}
		</div>
	{/each}
</div>
