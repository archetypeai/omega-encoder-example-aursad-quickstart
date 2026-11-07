<script>
	/**
	 * What the agent produces, and what our detector makes of it. Right side of the
	 * workbench, in the sibling monitors' order: the picture first (the robot cell, the
	 * embedding space, or the log), then the detection state under it, then the totals.
	 *
	 * The Omega Encoder agent returns embeddings only; the call (normal / alarm) is the
	 * frozen kNN's, made in the serving bridge.
	 */
	import Pane from '$lib/components/ui/patterns/pane/index.js';
	import { Separator } from '@archetypeai/ds-ui-svelte-console/primitives/separator';
	import * as Tooltip from '@archetypeai/ds-ui-svelte-console/primitives/tooltip';
	import * as Tabs from '@archetypeai/ds-ui-svelte-console/primitives/tabs';
	import CircleArrowDownIcon from '@lucide/svelte/icons/circle-arrow-down';
	import ScatterChartIcon from '@lucide/svelte/icons/chart-scatter';
	import BotIcon from '@lucide/svelte/icons/bot';
	import ListIcon from '@lucide/svelte/icons/list';
	import RobotCell from './robot-cell.svelte';
	import EmbeddingSpace from './embedding-space.svelte';
	import DetectionLog from './detection-log.svelte';
	import DetectionState from './detection-state.svelte';
	import RunControls from './run-controls.svelte';

	/** @type {{aursad: any, settingsOpen?: boolean, class?: string}} */
	let { aursad, settingsOpen = $bindable(false), class: className = '' } = $props();
	const s = $derived(aursad.state);
	const t = $derived(aursad.totals);
	const det = $derived(s.agent?.detector);
	const SUBTITLE = $derived(
		`Omega 1.5, served at window ${s.agent?.window ?? '…'} + kNN · Archetype AI platform, agent serving`
	);
	let view = $state('cell');

	const aside = $derived(
		view === 'cell'
			? "Each tightening's 1,024 rows go to a serving session of the Omega Encoder agent, which returns one 768-d embedding per channel per window. The frozen kNN (Stage 5) compares each window with the 150 normal tightenings' windows at the same position; the farthest is the tightening's score, and it alarms over the threshold. Callout 4 is muted: the agent embeds the joint currents, but the detector does not compare them."
			: view === 'embedding'
				? "The 600 library windows (150 normal tightenings, 4 windows each) in PCA 1-2 of the detector's joint states, and the live tightenings' windows through the same projection. Two dimensions of 4,608: a window far from the cloud here is far; one inside it can still be far in the others."
				: 'Every tightening that crossed the threshold, newest first. Labels stay hidden until you reveal them in Settings, or the replay has played to the end, as in Stage 7.'
	);

	const totals = $derived([
		{ label: 'Scored', value: `${t.scored} / ${s.status?.opCount ?? 90}` },
		{ label: 'Caught', value: t.truth ? `${t.truth.caught} / ${t.truth.anomalies}` : 'hidden' },
		{ label: 'False alarms', value: t.truth ? `${t.truth.falseAlarms} / ${t.truth.normals}` : 'hidden' },
		{ label: 'Per tightening', value: t.medianLatencyMs == null ? '—' : `${t.medianLatencyMs} ms` }
	]);
</script>

<Tabs.Root bind:value={view} class="flex min-h-0 flex-col {className}">
	<Pane variant="panel" title="Omega Encoder agent" icon={CircleArrowDownIcon} subtitle={SUBTITLE} class="relative min-h-0 flex-1">
		{#snippet titleAfter()}
			<Tooltip.Root>
				<Tooltip.Trigger variant="info" aria-label="About this view" />
				<Tooltip.Content class="max-w-xs">{aside}</Tooltip.Content>
			</Tooltip.Root>
		{/snippet}
		{#snippet actions()}
			<Tabs.List variant="segmented">
				<Tabs.Trigger value="cell" variant="icon" title="Robot cell" aria-label="Robot cell"><BotIcon /></Tabs.Trigger>
				<Tabs.Trigger value="embedding" variant="icon" title="Embedding space" aria-label="Embedding space"><ScatterChartIcon /></Tabs.Trigger>
				<Tabs.Trigger value="log" variant="icon" title="Alarms" aria-label="Alarms"><ListIcon /></Tabs.Trigger>
			</Tabs.List>
		{/snippet}

		<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
			<Tabs.Content value="cell" class="flex min-h-0 flex-1 flex-col p-4"><RobotCell {aursad} class="flex-1" /></Tabs.Content>
			<Tabs.Content value="embedding" class="flex min-h-0 flex-1 flex-col p-4"><EmbeddingSpace {aursad} class="flex-1" /></Tabs.Content>
			<Tabs.Content value="log" class="flex min-h-0 flex-1 flex-col p-4"><DetectionLog {aursad} class="flex-1" /></Tabs.Content>

			<Separator />

			<Pane title="Detection state" class="shrink-0">
				{#snippet titleAfter()}
					<Tooltip.Root>
						<Tooltip.Trigger variant="info" aria-label="How to read the detection state" />
						<Tooltip.Content class="max-w-sm">
							Current is the call on the last tightening: alarm when its worst window's kNN distance
							is over the threshold Stage 5 froze ({det ? det.threshold.toFixed(2) : '…'}, 5% false
							alarms on validation's normal tightenings). The bars under it are that tightening's
							windows. The strip is every tightening of the replay, oldest left; after the labels are
							revealed, a faulty one is underlined, so a red chip without a line is a false alarm and
							a green one with a line was missed.
						</Tooltip.Content>
					</Tooltip.Root>
				{/snippet}
				<DetectionState {aursad} />
				<div class="grid grid-cols-2 gap-x-6 gap-y-1 pt-2 pr-56 sm:grid-cols-4">
					{#each totals as x (x.label)}
						<div class="flex flex-col">
							<span class="font-mono text-2xs text-muted-foreground uppercase">{x.label}</span>
							<span class="font-mono text-sm tabular-nums">{x.value}</span>
						</div>
					{/each}
				</div>
			</Pane>
		</div>

		<div class="absolute right-4 bottom-4 z-10">
			<RunControls {aursad} bind:settingsOpen />
		</div>
	</Pane>
</Tabs.Root>
