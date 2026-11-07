<script>
	/**
	 * The app's processes and the MQTT topics between them, with the rate this browser
	 * tab observes on each: when something stops, it shows which hop. The LARCO
	 * monitor's diagram, with this app's processes and topics.
	 */
	/** @type {{aursad: any}} */
	let { aursad } = $props();
	const f = $derived(aursad.state.flows);
	const GOOD = 'var(--color-atai-good)';
	const MUTED = 'var(--color-muted-foreground)';
	const on = (/** @type {number} */ r) => (r > 0 ? GOOD : MUTED);
	const fmt = (/** @type {number} */ r) => (r > 0 ? `${r < 10 ? r.toFixed(1) : Math.round(r)} msg/s` : 'idle');
	const replayer = $derived(f['aursad/raw'] > 0 || !!aursad.state.status);
	const agentOn = $derived(aursad.state.agent?.phase === 'running');
	const win = $derived(aursad.state.agent?.window ?? 256);
</script>

<svg viewBox="0 0 860 400" class="w-full font-mono" role="img" aria-label="The app's processes and topics">
	<defs>
		<marker id="aursad-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
			<path d="M0,0 L8,4 L0,8 z" fill={MUTED} />
		</marker>
	</defs>
	{#snippet box(
		/** @type {number} */ x,
		/** @type {number} */ y,
		/** @type {number} */ w,
		/** @type {string} */ title,
		/** @type {string[]} */ lines,
		/** @type {boolean} */ alive
	)}
		<rect {x} {y} width={w} height={34 + lines.length * 16} rx="2" fill="var(--color-background)" stroke="var(--color-border)" />
		<circle cx={x + 14} cy={y + 17} r="4" fill={on(alive ? 1 : 0)} />
		<text x={x + 26} y={y + 21} class="text-sm" fill="var(--color-foreground)">{title}</text>
		{#each lines as l, i (i)}
			<text x={x + 26} y={y + 40 + i * 16} class="text-2xs" fill={MUTED}>{l}</text>
		{/each}
	{/snippet}
	{#snippet edge(
		/** @type {string} */ d,
		/** @type {string} */ label,
		/** @type {number} */ rate,
		/** @type {number} */ lx,
		/** @type {number} */ ly
	)}
		<path {d} fill="none" stroke="var(--color-border)" stroke-width="1.5" marker-end="url(#aursad-arrow)" />
		{#if rate > 0}
			<circle r="3.5" fill={GOOD}><animateMotion dur="1.4s" repeatCount="indefinite" path={d} /></circle>
		{/if}
		<text x={lx} y={ly} class="text-2xs" fill={on(rate)}>{label} · {fmt(rate)}</text>
	{/snippet}

	{@render box(20, 20, 300, 'replayer (node)', ['data/roles/delivery/<tightening>.csv', '1,024 rows, in blocks of 32, at the pace'], replayer)}
	{@render box(540, 20, 300, 'serving bridge (node)', [`POST /query: one tightening, window ${win}`, 'kNN detector (frozen, Stage 5)', 'the API key stays here'], agentOn)}
	{@render box(230, 180, 400, 'mosquitto · tcp :1893 · ws :9011', [], aursad.state.connected)}
	{@render box(180, 300, 500, 'web app (this tab, mqtt.js over WebSockets)', ['robot cell · detection state · embedding space · log'], aursad.state.connected)}

	{@render edge('M 170,104 C 170,150 220,190 228,196', 'aursad/raw · op', f['aursad/raw'] + f['aursad/op'], 40, 140)}
	{@render edge('M 632,196 C 680,170 690,130 690,120', 'aursad/raw · op', f['aursad/raw'] + f['aursad/op'], 600, 140)}
	{@render edge('M 780,120 C 780,160 700,200 632,208', 'omega/results', f['omega/results'], 710, 172)}
	{@render edge('M 430,214 L 430,298', 'aursad/* · omega/*', f['aursad/raw'] + f['omega/results'] + f['aursad/status'], 440, 262)}
	{@render edge('M 300,298 C 300,260 290,230 290,216', 'aursad/control', f['aursad/control'], 120, 262)}
</svg>
