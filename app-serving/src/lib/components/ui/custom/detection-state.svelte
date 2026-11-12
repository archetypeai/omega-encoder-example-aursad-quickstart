<script>
	/**
	 * The detection state, in the RED pump monitor's shape: the current call and the
	 * alarm count as badges, then a strip with one chip per tightening of the replay
	 * (pending ones grey), oldest left. Between them, the last tightening's windows: the
	 * agent embeds 1,024 rows as 1,024/W windows, our kNN scores each, and the worst one
	 * is the tightening's score.
	 *
	 * Chips are coloured by the detector's call only. Once the labels are revealed, a
	 * faulty tightening gets a mark under its chip, so caught, missed and false alarms
	 * can be told apart without the label ever colouring a call.
	 */
	import { Badge } from '@archetypeai/ds-ui-svelte-console/primitives/badge';
	import { scoreTone, SCORE_META } from '$lib/scores.js';
	import { CLASS_LABEL } from '$lib/stores/aursad.svelte.js';
	import { cn } from '$lib/utils';

	/** @type {{aursad: any, class?: string}} */
	let { aursad, class: className = '' } = $props();
	const s = $derived(aursad.state);
	const n = $derived(s.status?.opCount ?? 90);
	const byOp = $derived(new Map(s.results.map((/** @type {any} */ r) => [r.op, r])));
	const last = $derived([...s.results].reverse().find((/** @type {any} */ r) => r.score !== undefined));
	const alarms = $derived(s.results.filter((/** @type {any} */ r) => r.alarm).length);
	const NAMES = ['before', 'driving', 'finishing', 'after'];
	const win = $derived(s.agent?.window ?? 256);
</script>

{#snippet pair(/** @type {string} */ label, /** @type {import('svelte').Snippet} */ children)}
	<div class="flex min-w-0 items-center gap-2">
		<span class="shrink-0 font-mono text-[11px] tracking-wider text-muted-foreground uppercase">{label}</span>
		{@render children()}
	</div>
{/snippet}

<div class={cn('flex flex-col gap-3', className)}>
	<div class="flex flex-wrap items-center justify-between gap-3">
		{#snippet current()}
			{#if last}
				{@const tone = scoreTone(last.score, last.threshold)}
				<Badge variant="status" class="text-xs transition-none" style="color: {tone.color}; border-color: {tone.color}">
					{last.alarm ? 'alarm' : 'normal'}
				</Badge>
				<span class="font-mono text-xs text-muted-foreground tabular-nums">
					#{last.op + 1} · score {last.score.toFixed(2)} / {last.threshold.toFixed(2)}
				</span>
			{:else}
				<Badge variant="status" class="border-border text-xs text-muted-foreground">
					{s.agent?.phase === 'running' || !s.agent ? 'awaiting' : s.agent.phase}
				</Badge>
			{/if}
		{/snippet}
		{@render pair('Current', current)}
		{#snippet alarm()}
			<Badge
				variant="status"
				class="text-xs {alarms ? '' : 'border-border text-muted-foreground'}"
				style={alarms ? `color: ${SCORE_META.anomaly.color}; border-color: ${SCORE_META.anomaly.color}` : undefined}
			>
				{alarms || '—'}
			</Badge>
		{/snippet}
		{@render pair('Alarms', alarm)}
	</div>

	{#if last?.windowScores}
		<div class="grid gap-2" style="grid-template-columns: repeat({last.windowScores.length}, 1fr)">
			{#each last.windowScores as v, j (j)}
				{@const t = scoreTone(v, last.threshold)}
				<div class="flex flex-col gap-1" title="window {j + 1}: rows {j * win}–{(j + 1) * win - 1}">
					<div class="h-1.5 w-full rounded-[1px] bg-muted-foreground/15">
						<div class="h-full rounded-[1px]" style="width: {Math.min(100, (v / (last.threshold * 1.4)) * 100)}%; background: {t.color}; opacity: {j === last.worst ? 1 : 0.5}"></div>
					</div>
					<span class="font-mono text-2xs text-muted-foreground tabular-nums {j === last.worst ? 'text-foreground' : ''}">
						{j + 1}{last.windowScores.length === 4 ? ` · ${NAMES[j]}` : ''} · {v.toFixed(2)}
					</span>
				</div>
			{/each}
		</div>
	{/if}

	<div class="flex w-full min-w-0 items-end gap-[3px]" role="list" aria-label="Tightenings of the replay">
		{#each Array.from({ length: n }, (_, i) => i) as i (i)}
			{@const r = byOp.get(i)}
			{@const label = r && s.labels.revealed ? s.labels.labels[r.file] : null}
			<div role="listitem" class="flex min-w-0 flex-1 flex-col items-center gap-[3px]">
				<div
					class="h-8 w-full rounded-[1px] {r?.score === undefined ? 'bg-muted-foreground/20' : ''}"
					style={r?.score !== undefined ? `background: ${scoreTone(r.score, r.threshold).color}` : ''}
					title={r?.score !== undefined
						? `#${i + 1} ${r.file} · score ${r.score.toFixed(3)}${r.alarm ? ' · alarm' : ''}${label ? ` · ${CLASS_LABEL[label] ?? label}` : ''}`
						: `#${i + 1} pending`}
				></div>
				<div class="h-[3px] w-full rounded-[1px] {label && label !== 'normal' ? 'bg-foreground' : ''}"></div>
			</div>
		{/each}
	</div>
	<div class="flex justify-between text-[11px] text-muted-foreground tabular-nums">
		<span>tightening 1</span>
		<span>
			{s.labels.revealed ? 'green: normal · red: alarm · underline: a faulty tightening (label)' : 'green: normal · red: alarm'}
		</span>
		<span>{n}</span>
	</div>
</div>
